"""Comprehensive Verification Suite for Live Bounded-Agentic Plan Integration.

Validates:
1. Authoritative Plan Creation & Persistence:
   - ensure_session_script_plan generates pinned script_plan and synchronizes InterviewQuestion rows.
   - Idempotency via input_hash and generation run.
   - In-progress session protection (never overwrites running questions).
2. Plan Skeleton & Variant Handling:
   - anchor_alt marked kind="anchor_alt", is_required=False, parent_question_id set.
   - anchor_alt excluded from question_order and get_ordered_slots() (never duplicated in normal progression).
   - Custom screening slots are addressable and not skipped.
3. Conductor Plan-Driven Opening:
   - SessionStart speaks exact stored plan greeting and sets current_slot_id.
   - GREETING_RESPONSE TurnEnd transitions directly to INTRO speaking background question (no duplicate agenda).
   - Legacy plans without script_plan maintain backward-compatible GREETING -> AGENDA -> INTRO flow.
4. Stable Plan ID & Parent Slot Tracking:
   - ConductorState tracks current_slot_id and parent_slot_id.
   - RequestDecision carries slot_id and parent_slot_id.
   - On follow-up, state.parent_slot_id preserves parent anchor slot ID.
   - ADVANCE resolves by planned_question_id and resets parent_slot_id.
5. Custom Screening Slot Progression:
   - "Custom Screening" indexed in skill_names_ordered and reached before Candidate Q&A.
6. Candidate Q&A Answer Grounding:
   - Selector CANDIDATE_QA evaluates candidate's committed question using authoritative job facts.
   - Suppresses ack on deferral without invalidating answer.
7. Speculation Guard in Plan Mode:
   - Speculative replies are disabled when script_plan is active.
8. WebSocket Privacy:
   - Outbound UIStatus frames strip expected_key_points, rubrics, and internal plan hints.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    BlueprintExpectation,
    BlueprintQuestion,
    BlueprintSection,
    CandidatePersonalization,
    CandidateResume,
    InterviewBlueprint,
    InterviewGenerationRun,
    InterviewQuestion,
    InterviewSession,
    JobApplication,
    JobCustomQuestion,
    JobPosting,
    JobSkill,
    User,
)
from backend.app.services.interview_v2.conductor import (
    APPROVED_QA_DEFERRAL,
    AckReady,
    BotSpeechDone,
    CommitButton,
    ConductorPhase,
    ConductorState,
    DecisionReady,
    EmitUI,
    PlanQuestion,
    ReadyButton,
    RequestDecision,
    SessionStart,
    Speak,
    StartSpeculativeReply,
    TurnEnd,
    step,
    validate_and_apply_decision,
    validate_qa_decision,
)
from backend.app.services.interview_v2.context_hydrator import (
    HydratedInterviewContext,
    hydrate_interview_context,
)
from backend.app.services.interview_v2.plan_schema import (
    PlanSlot,
    ScriptPlan,
    build_plan_skeleton,
    compute_plan_input_hash,
)
from backend.app.services.interview_v2.plan_writer import (
    ensure_session_script_plan,
    generate_or_load_script_plan,
)
from backend.app.services.interview_v2.runner import (
    SessionRunner,
    build_script,
)
from backend.app.services.interview_v2.selector import (
    SelectorInput,
    SelectorOutput,
    _generate_plan_aware_fallback,
    select_next_interview_action,
)


# =============================================================================
# 1. Authoritative Plan Creation & Persistence
# =============================================================================

@pytest.mark.asyncio
async def test_ensure_session_script_plan_e2e():
    """Verify fresh blueprint-backed application produces a pinned ScriptPlan

    before candidate starts, synchronizes InterviewQuestion rows, and protects in-progress sessions.
    """
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=f"plan_test_{uuid.uuid4().hex[:6]}@example.com",
            full_name="Alex Turner",
            password_hash="fake",
        )
        db.add(user)

        job = JobPosting(
            id=str(uuid.uuid4()),
            job_title="Senior Backend Systems Engineer",
            department="Infrastructure",
            seniority_level="Senior",
            job_description="Architect distributed streaming infrastructure.",
            interview_duration_mins=20,
            status="active",
        )
        db.add(job)

        skill_1 = JobSkill(
            id=str(uuid.uuid4()),
            job_id=job.id,
            name="Distributed Systems",
            priority_tier="P0",
            weight_percentage=60.0,
            rubric_l3="Designs consistent replication and partition tolerance strategies.",
        )
        skill_2 = JobSkill(
            id=str(uuid.uuid4()),
            job_id=job.id,
            name="Async Python",
            priority_tier="P0",
            weight_percentage=40.0,
            rubric_l3="Uses asyncio and multiprocessing appropriately for concurrency.",
        )
        db.add_all([skill_1, skill_2])

        cq = JobCustomQuestion(
            id=str(uuid.uuid4()),
            job_id=job.id,
            question_text="How do you handle production on-call escalations?",
            is_required=True,
        )
        db.add(cq)

        bp = InterviewBlueprint(
            id=str(uuid.uuid4()),
            job_id=job.id,
            version=1,
            status="approved",
            total_duration_mins=20,
            active_skill_mins=14.0,
            fixed_overhead_mins=6.0,
        )
        db.add(bp)
        await db.flush()

        # Add blueprint sections with anchor and anchor_alt
        bp_sec = BlueprintSection(
            id=str(uuid.uuid4()),
            blueprint_id=bp.id,
            title="Distributed Systems Section",
            skill_name="Distributed Systems",
            skill_id=skill_1.id,
            section_type="skill",
            order_index=0,
            allocated_minutes=10,
        )
        db.add(bp_sec)
        await db.flush()

        bp_q_anchor = BlueprintQuestion(
            id=str(uuid.uuid4()),
            section_id=bp_sec.id,
            question_role="anchor",
            question_text="How do you design a reliable retry mechanism using exponential backoff?",
            order_index=0,
        )
        bp_q_alt = BlueprintQuestion(
            id=str(uuid.uuid4()),
            section_id=bp_sec.id,
            question_role="anchor_alt",
            question_text="If a third-party service lacks idempotent endpoints, how do you prevent duplicate side-effects?",
            order_index=1,
        )
        bp_exp = BlueprintExpectation(
            id=str(uuid.uuid4()),
            section_id=bp_sec.id,
            expectation_text="Explains jitter to prevent thundering herd",
            order_index=0,
        )
        db.add_all([bp_q_anchor, bp_q_alt, bp_exp])

        job.active_blueprint_id = bp.id
        await db.flush()

        app = JobApplication(
            id=str(uuid.uuid4()),
            job_id=job.id,
            candidate_id=user.id,
            full_name="Alex Turner",
            email=user.email,
            status="scheduled",
            self_reported_experience_years=7.0,
        )
        db.add(app)
        await db.flush()

        session = InterviewSession(
            id=str(uuid.uuid4()),
            application_id=app.id,
            job_id=job.id,
            status="scheduled",
            duration_planned_mins=20,
            runtime_state={},
        )
        db.add(session)
        await db.commit()

        # 1. Call ensure_session_script_plan
        async def mock_script_writer(system_prompt: str, user_prompt: str):
            # Deterministic pass through: returns empty slots to let skeleton prevail
            return {"slots": []}

        plan = await ensure_session_script_plan(db, session, llm_fn=mock_script_writer)
        assert plan is not None
        assert isinstance(plan, ScriptPlan)
        assert plan.application_id == app.id
        assert plan.job_id == job.id

        # 2. Check session.runtime_state["script_plan"]
        sess_stmt = select(InterviewSession).where(InterviewSession.id == session.id)
        sess_db = (await db.execute(sess_stmt)).scalar_one()
        assert "script_plan" in sess_db.runtime_state
        assert sess_db.runtime_state["script_plan"]["plan_id"] == plan.plan_id

        # 3. Verify synchronized InterviewQuestion rows
        q_stmt = select(InterviewQuestion).where(InterviewQuestion.session_id == session.id).order_by(InterviewQuestion.question_index)
        db_qs = (await db.execute(q_stmt)).scalars().all()
        assert len(db_qs) >= 5  # greeting, background, technical, custom, qa, closing

        # Verify anchor_alt is NOT in normal question sequence (no duplicates)
        q_texts = [q.question_text for q in db_qs]
        assert bp_q_anchor.question_text in q_texts
        assert bp_q_alt.question_text not in q_texts

        # 4. Idempotency: Second call returns existing plan
        plan_2 = await ensure_session_script_plan(db, session)
        assert plan_2.plan_id == plan.plan_id

        # 5. In-progress session protection: question rows are not replaced
        sess_db.status = "in_progress"
        await db.commit()

        orig_q_ids = [q.id for q in db_qs]
        plan_3 = await ensure_session_script_plan(db, sess_db, force_regenerate=True, llm_fn=mock_script_writer)
        db_qs_after = (await db.execute(q_stmt)).scalars().all()
        assert [q.id for q in db_qs_after] == orig_q_ids


# =============================================================================
# 2. Plan Skeleton & Variant Grouping
# =============================================================================

def test_plan_skeleton_anchor_alt_variant_grouping_and_custom_screening():
    """Verify anchor_alt is kind='anchor_alt', is_required=False, has parent_question_id,

    and is excluded from question_order and get_ordered_slots().
    """
    context = HydratedInterviewContext(
        application_id="app_v1",
        job_id="job_v1",
        candidate_full_name="Morgan Reed",
        candidate_first_name="Morgan",
        job_title="Distributed Systems Engineer",
        interview_duration_mins=20,
        skills=[
            {
                "id": "sk_ds",
                "name": "Distributed Systems",
                "priority_tier": "P0",
                "weight_percentage": 100.0,
            }
        ],
        custom_questions=[
            {
                "id": "cq_1",
                "question_text": "What is your experience managing live database rollbacks?",
                "is_required": True,
            }
        ],
        blueprint_sections=[
            {
                "title": "Distributed Systems",
                "skill_name": "Distributed Systems",
                "section_type": "skill",
                "questions": [
                    {
                        "question_role": "anchor",
                        "question_text": "How do you achieve linearizable reads in a distributed cluster?",
                    },
                    {
                        "question_role": "anchor_alt",
                        "question_text": "If consensus is unavailable, how do you handle degraded reads?",
                    },
                    {
                        "question_role": "probe",
                        "question_text": "How does lease expiration prevent stale reads?",
                    },
                ],
                "expectations": [
                    {"expectation_text": "Mentions Raft or Paxos leader leases"}
                ],
            }
        ],
    )

    skeleton = build_plan_skeleton(context)

    # 1. Inspect slots
    anchor_slot = next((s for s in skeleton.slots if s.kind == "anchor"), None)
    alt_slot = next((s for s in skeleton.slots if s.kind == "anchor_alt"), None)
    cq_slot = next((s for s in skeleton.slots if s.kind == "custom"), None)

    assert anchor_slot is not None
    assert alt_slot is not None
    assert cq_slot is not None

    # 2. Variant contract
    assert alt_slot.is_required is False
    assert alt_slot.parent_question_id == anchor_slot.id
    assert alt_slot.variant_group == "Distributed Systems_variant"

    # 3. Exclusion from sequential order
    assert alt_slot.id not in skeleton.question_order
    ordered_slot_ids = [s.id for s in skeleton.get_ordered_slots()]
    assert alt_slot.id not in ordered_slot_ids
    assert anchor_slot.id in ordered_slot_ids
    assert cq_slot.id in ordered_slot_ids


# =============================================================================
# 3. Conductor Opening: Plan-Driven vs Legacy
# =============================================================================

def test_conductor_plan_driven_opening_speaks_exact_greeting_and_skips_duplicate_agenda():
    """Verify that when a plan is provided, SessionStart speaks the exact plan greeting,

    and GREETING_RESPONSE TurnEnd transitions directly to INTRO without inserting AGENDA.
    """
    greeting_text = (
        "Hi Morgan! Welcome to your interview for the Distributed Systems Engineer role. "
        "Today we will cover Distributed Systems and Database Rollbacks, followed by time for any questions. "
        "Does that sound good?"
    )
    background_text = "To start off, could you introduce yourself and tell me about your background with distributed consensus?"
    tech_anchor_text = "How do you achieve linearizable reads in a distributed cluster?"

    plan = {
        "script_plan": {"plan_id": "test_plan_01"},
        "questions": [
            {
                "id": "slot_greeting",
                "question_index": 0,
                "stage": "greeting",
                "kind": "greeting",
                "skill_name": "General",
                "question_text": greeting_text,
            },
            {
                "id": "slot_intro",
                "question_index": 1,
                "stage": "background",
                "kind": "background",
                "skill_name": "General",
                "question_text": background_text,
            },
            {
                "id": "slot_tech",
                "question_index": 2,
                "stage": "technical",
                "kind": "anchor",
                "skill_name": "Distributed Systems",
                "question_text": tech_anchor_text,
            },
            {
                "id": "slot_closing",
                "question_index": 3,
                "stage": "closing",
                "kind": "closing",
                "skill_name": "General",
                "question_text": "Thank you for your time. Have a great day!",
            },
        ],
    }

    state = ConductorState()
    state, effects = step(state, SessionStart(session_id="sess_plan_01", plan=plan, now_ms=1000))

    # 1. Speaks exact greeting text
    assert state.phase == ConductorPhase.GREETING
    speak_effect = next(e for e in effects if isinstance(e, Speak))
    assert speak_effect.text == greeting_text
    assert state.current_slot_id == "slot_greeting"

    # Finish greeting audio playback
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    assert state.phase == ConductorPhase.GREETING_RESPONSE

    # 2. Candidate answers greeting: "Sounds great, ready to begin."
    state, effects2 = step(state, TurnEnd(text="Sounds great, ready to begin.", turn_id="t_greet", now_ms=2500))

    # Direct transition to INTRO, speaking the stored background question (NO duplicate AGENDA!)
    assert state.phase == ConductorPhase.INTRO
    assert state.current_slot_id == "slot_intro"
    speak_intro = next(e for e in effects2 if isinstance(e, Speak))
    assert background_text in speak_intro.text


def test_conductor_legacy_plan_maintains_agenda_phase():
    """Verify that legacy plans without script_plan continue to transition through

    GREETING -> AGENDA -> INTRO as tested by legacy test suites.
    """
    legacy_plan = {
        "questions": [
            {
                "question_index": 0,
                "kind": "welcome",
                "skill_name": "Welcome",
                "question_text": "Hi, I'm your interviewer. How are you today?",
            },
            {
                "question_index": 1,
                "kind": "intro_hook",
                "skill_name": "Introduction",
                "question_text": "To start off, please introduce yourself.",
            },
            {
                "question_index": 2,
                "kind": "anchor",
                "skill_name": "Python",
                "question_text": "How do you handle concurrency in Python?",
            },
        ]
    }

    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="sess_legacy", plan=legacy_plan, now_ms=1000))
    assert state.phase == ConductorPhase.GREETING

    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    assert state.phase == ConductorPhase.GREETING_RESPONSE

    # Candidate replies: legacy moves to AGENDA
    state, _ = step(state, TurnEnd(text="I am doing well, thanks.", turn_id="t_leg", now_ms=2500))
    assert state.phase == ConductorPhase.AGENDA


# =============================================================================
# 4. Stable Plan ID & Parent Slot Tracking
# =============================================================================

def test_conductor_stable_id_and_parent_slot_tracking():
    """Verify ConductorState tracks current_slot_id and parent_slot_id,

    and ADVANCE resolves next question by planned_question_id.
    """
    state = ConductorState(
        session_id="sess_track_01",
        phase=ConductorPhase.SKILL_ANCHOR,
        current_skill_index=0,
        skill_names=["Distributed Systems", "Database Design"],
        current_slot_id="slot_ds_anchor",
        parent_slot_id=None,
        questions=[
            PlanQuestion(
                question_index=2,
                kind="anchor",
                skill_name="Distributed Systems",
                question_text="How do you handle distributed consensus?",
                id="slot_ds_anchor",
                stage="technical",
            ),
            PlanQuestion(
                question_index=3,
                kind="anchor",
                skill_name="Database Design",
                question_text="How do you design composite indexes?",
                id="slot_db_anchor",
                stage="technical",
            ),
        ],
    )

    # 1. Follow-up action preserves parent_slot_id
    followup_decision = {
        "action": "follow_up",
        "question": "How do you handle network partitions specifically?",
        "ack": "Understood.",
    }
    state, effects = validate_and_apply_decision(state, followup_decision, now_ms=5000)
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    assert state.parent_slot_id == "slot_ds_anchor"
    assert state.current_slot_id is None

    # 2. Advance action resolves next question by planned_question_id
    advance_decision = {
        "action": "new_topic",
        "planned_question_id": "slot_db_anchor",
        "question": "How do you design composite indexes?",
        "target_skill": "Database Design",
        "ack": "Moving forward.",
    }
    state, effects2 = validate_and_apply_decision(state, advance_decision, now_ms=8000)
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.current_slot_id == "slot_db_anchor"
    assert state.parent_slot_id is None
    speak = next(e for e in effects2 if isinstance(e, Speak))
    assert "How do you design composite indexes?" in speak.text


# =============================================================================
# 5. Custom Screening Slot Addressable & Not Skipped
# =============================================================================

def test_custom_screening_slot_indexed_and_not_skipped():
    """Verify that custom screening questions (kind='custom') are indexed

    into skill_names_ordered and reachable during normal progression.
    """
    plan = {
        "questions": [
            {
                "id": "q_anchor",
                "question_index": 2,
                "stage": "technical",
                "kind": "anchor",
                "skill_name": "Python",
                "question_text": "How do you use asyncio?",
            },
            {
                "id": "q_custom",
                "question_index": 3,
                "stage": "custom_screening",
                "kind": "custom",
                "skill_name": "Custom Screening",
                "question_text": "Are you willing to participate in a 24/7 on-call rotation?",
            },
            {
                "id": "q_qa",
                "question_index": 4,
                "stage": "candidate_qa",
                "kind": "candidate_qa",
                "skill_name": "Candidate Q&A",
                "question_text": "What questions do you have for us?",
            },
        ]
    }

    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="sess_custom", plan=plan, now_ms=1000))

    # "Custom Screening" must be indexed in skill_names
    assert "Custom Screening" in state.skill_names
    assert state.skill_questions["Custom Screening"]["anchor"].question_text == "Are you willing to participate in a 24/7 on-call rotation?"


# =============================================================================
# 6. Candidate Q&A Grounded Answer & Deferral Ack Suppression
# =============================================================================

@pytest.mark.asyncio
async def test_candidate_qa_evaluates_with_job_facts_and_suppresses_ack_on_deferral():
    """Verify Candidate Q&A answers the actual candidate question via job facts

    and suppresses ack on deferrals without failing.
    """
    runner = SessionRunner(
        session_id="sess_qa_01",
        script={
            "job_record": {
                "title": "Senior Reliability Engineer",
                "description": "We build with Python 3.12, AWS ECS, and PostgreSQL.",
                "skills": ["Python", "AWS", "PostgreSQL"],
                "seniority": "Senior",
            },
            "questions": [],
        },
    )

    # 1. Answerable question
    prompt_sys, prompt_user, facts = runner._build_qa_prompt("What database do you use in production?", None)
    assert any("PostgreSQL" in val for val in facts.values())

    # 2. Deferral question (compensation / salary)
    prompt_sys_def, prompt_user_def, facts_def = runner._build_qa_prompt("What is the exact salary range for this role?", None)
    assert not any("salary" in val.lower() or "compensation" in val.lower() for val in facts_def.values())

    # 3. Verify fallback in validate_and_apply_decision
    state = ConductorState(
        session_id="sess_qa_def",
        phase=ConductorPhase.CANDIDATE_QA,
        job_record={"title": "Staff Engineer"},
        committed_answer="What is the compensation package?",
    )
    unsupported_decision = {
        "action": "candidate_qa",
        "question": "I don't have that detail on hand, but the hiring team will follow up on that.",
        "ack": "Understood.",
    }
    state, effects = validate_and_apply_decision(state, unsupported_decision, now_ms=10000)
    speak = next(e for e in effects if isinstance(e, Speak))
    # Ack must be suppressed on deferral
    assert speak.ack_text == ""
    assert "hiring team will follow up" in speak.text


# =============================================================================
# 7. Speculation Guard in Plan Mode
# =============================================================================

@pytest.mark.asyncio
async def test_speculation_disabled_in_plan_mode():
    """Verify speculative reply generation is immediately disabled when a ScriptPlan is present."""
    plan = ScriptPlan(
        plan_id="plan_spec_test",
        application_id="app_01",
        job_id="job_01",
        input_hash="hash_01",
        slots=[],
    )

    runner = SessionRunner(
        session_id="sess_spec",
        script={"script_plan": plan.model_dump(), "questions": []},
    )
    assert runner.script_plan is not None

    with patch("backend.app.services.interview_v2.runner.generate_director_decision") as mock_director:
        spec_event = StartSpeculativeReply(token="spec_01", source_text="I use Kafka for streaming.")
        await runner._handle_start_speculative_reply(spec_event)

        # Director was never called because speculation is bypassed in plan mode
        mock_director.assert_not_called()
        assert runner.spec_decision is None


# =============================================================================
# 8. WebSocket Privacy: No Rubrics or Key Points Sent
# =============================================================================

@pytest.mark.asyncio
async def test_websocket_privacy_filters_rubrics_and_expected_key_points():
    """Verify that EmitUI frames transmitted over WebSocket never include hidden

    expected_key_points, rubric_anchor_ids, or coverage requirements.
    """
    mock_ws = AsyncMock()

    runner = SessionRunner(
        session_id="sess_privacy",
        script={"questions": []},
        websocket=mock_ws,
    )

    leaky_payload = {
        "display_question": "Explain consistency models in distributed datastores.",
        "spoken_text": "Explain consistency models in distributed datastores.",
        "expected_key_points": ["Linearizability", "Eventual consistency trade-offs", "PACELC theorem"],
        "rubric_anchor_ids": ["rubric_l4_strong"],
        "coverage_requirements": [{"skill": "Distributed Systems", "weight": 60}],
        "phase": "technical",
    }

    emit_effect = EmitUI(status="technical", payload=leaky_payload)
    await runner._handle_emit_ui(emit_effect)

    mock_ws.send_json.assert_called_once()
    call_args = mock_ws.send_json.call_args[0][0]

    assert call_args["type"] == "UIStatus"
    sent_payload = call_args["payload"]
    assert "display_question" in sent_payload
    assert "expected_key_points" not in sent_payload
    assert "rubric_anchor_ids" not in sent_payload
    assert "coverage_requirements" not in sent_payload


# =============================================================================
# 9. Candidate Q&A Supported vs Unsupported End-to-End
# =============================================================================

@pytest.mark.asyncio
async def test_candidate_qa_supported_answers_from_job_facts_and_speaks_answer():
    """Verify supported Candidate Q&A uses job facts, emits grounded AckReady,
    and validate_and_apply_decision speaks the validated answer rather than deferral.
    """
    job_record = {
        "title": "Lead Platform Engineer",
        "seniority": "Staff",
        "description": "We run distributed microservices using Go and PostgreSQL on Google Cloud Platform.",
        "skills": ["Go", "PostgreSQL", "Google Cloud Platform"],
    }
    script = {
        "job_record": job_record,
        "questions": [],
    }
    runner = SessionRunner(
        session_id="sess_qa_supp",
        script=script,
        llm_fn=None,
    )
    req = RequestDecision(
        token="tok_qa_supp",
        skill="Candidate Q&A",
        question_text="Do you have any questions for me?",
        answer_text="What primary database engine do you run in production?",
    )

    llm_return = {
        "ack": "Understood regarding the production database.",
        "answer": "We run PostgreSQL on Google Cloud Platform for all primary transactional datastores. Anything else?",
        "source_facts": ["description_fact_001"],
    }
    with patch(
        "backend.app.services.interview_v2.runner.stream_decision_with_ack_first",
        new_callable=AsyncMock,
        return_value=(llm_return, {"ttft_ms": 120}),
    ):
        await runner._call_decision_llm(req)

    dec_msg = None
    ack_msg = None
    while not runner.queue.empty():
        msg = runner.queue.get_nowait()
        if isinstance(msg, DecisionReady):
            dec_msg = msg
        elif isinstance(msg, AckReady):
            ack_msg = msg

    assert dec_msg is not None
    assert dec_msg.decision["action"] == "candidate_qa"
    assert "PostgreSQL" in dec_msg.decision["question"]
    assert APPROVED_QA_DEFERRAL not in dec_msg.decision["question"]
    assert ack_msg is not None
    assert ack_msg.text != ""

    # Test that validate_and_apply_decision speaks the exact answer
    state = ConductorState(
        session_id="sess_qa_supp",
        phase=ConductorPhase.CANDIDATE_QA,
        job_record=job_record,
        committed_answer="What primary database engine do you run in production?",
        decision_token="tok_qa_supp",
    )
    state, effects = validate_and_apply_decision(state, dec_msg.decision, now_ms=5000)
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "PostgreSQL" in speak.text
    assert APPROVED_QA_DEFERRAL not in speak.text


@pytest.mark.asyncio
async def test_candidate_qa_unsupported_salary_falls_back_to_deferral_with_no_ack():
    """Verify compensation/salary query returns APPROVED_QA_DEFERRAL and emits NO ack."""
    job_record = {
        "title": "Lead Platform Engineer",
        "description": "We run distributed microservices using Go.",
        "skills": ["Go"],
    }
    runner = SessionRunner(
        session_id="sess_qa_salary",
        script={"job_record": job_record, "questions": []},
        llm_fn=None,
    )
    req = RequestDecision(
        token="tok_qa_salary",
        skill="Candidate Q&A",
        question_text="Do you have any questions for me?",
        answer_text="What is the base salary and equity compensation for this role?",
    )
    llm_return = {
        "ack": "Understood, asking about compensation.",
        "answer": "The compensation is $200,000 base with 0.1% equity. Anything else?",
        "source_facts": ["job_title"],
    }
    with patch(
        "backend.app.services.interview_v2.runner.stream_decision_with_ack_first",
        new_callable=AsyncMock,
        return_value=(llm_return, {"ttft_ms": 110}),
    ):
        await runner._call_decision_llm(req)

    dec_msg = None
    ack_msg = None
    while not runner.queue.empty():
        msg = runner.queue.get_nowait()
        if isinstance(msg, DecisionReady):
            dec_msg = msg
        elif isinstance(msg, AckReady):
            ack_msg = msg

    assert dec_msg is not None
    assert dec_msg.decision["action"] == "candidate_qa"
    assert dec_msg.decision["question"] == APPROVED_QA_DEFERRAL
    assert dec_msg.decision["ack"] == ""
    assert ack_msg is None


@pytest.mark.asyncio
async def test_candidate_qa_length_violation_falls_back_to_deferral():
    """Verify answers exceeding 35 words fall back to APPROVED_QA_DEFERRAL."""
    job_record = {
        "title": "Engineer",
        "description": "We build web software with Python.",
        "skills": ["Python"],
    }
    long_answer = " ".join(["Python"] * 40)
    decision = {
        "ack": "Got it.",
        "answer": long_answer,
        "source_facts": ["description_fact_001"],
    }
    eff_ans, eff_ack, facts = validate_qa_decision(
        decision,
        {"description_fact_001": "We build web software with Python."},
        "What language do you use?",
    )
    assert eff_ans == APPROVED_QA_DEFERRAL
    assert eff_ack == ""


# =============================================================================
# 10. Opening Flow: ReadyButton and CommitButton speak stored background question
# =============================================================================

def test_ready_and_commit_buttons_speak_stored_background_question():
    """Verify ReadyButton and CommitButton both advance to stored background question,
    set current_slot_id to the background slot ID, and set current_question_index to its index.
    """
    bg_slot_id = "slot_bg_01"
    bg_question_text = "To begin, tell me about your background leading distributed teams."
    questions = [
        PlanQuestion(
            id="slot_greet_01",
            question_index=0,
            kind="greeting",
            stage="greeting",
            skill_name="General",
            question_text="Hello! Welcome to your interview today.",
        ),
        PlanQuestion(
            id=bg_slot_id,
            question_index=1,
            kind="background",
            stage="background",
            skill_name="General",
            question_text=bg_question_text,
        ),
        PlanQuestion(
            id="slot_tech_01",
            question_index=2,
            kind="anchor",
            stage="technical",
            skill_name="Distributed Systems",
            question_text="How do you handle consensus?",
        ),
    ]

    for btn_event in (ReadyButton(now_ms=1500), CommitButton(now_ms=1500)):
        state = ConductorState(
            session_id=f"sess_{type(btn_event).__name__}",
            phase=ConductorPhase.GREETING_RESPONSE,
            questions=list(questions),
            current_slot_id="slot_greet_01",
            current_question_index=0,
        )
        new_state, effects = step(state, btn_event)
        assert new_state.phase == ConductorPhase.INTRO
        assert new_state.current_slot_id == bg_slot_id
        assert new_state.current_question_index == 1

        speak = next(e for e in effects if isinstance(e, Speak))
        assert speak.question_text == bg_question_text
        assert speak.text == bg_question_text


# =============================================================================
# 11. anchor_alt: Retained in build_script, indexed, and chosen on no_experience
# =============================================================================

def test_anchor_alt_indexed_in_conductor_and_selected_on_no_experience():
    """Verify anchor_alt is retained by build_script(), indexed by SessionStart,
    skipped in normal sequential progression, and chosen when no_experience=True.
    """
    plan = ScriptPlan(
        plan_id="plan_alt_test",
        application_id="app_alt",
        job_id="job_alt",
        input_hash="hash_alt",
        question_order=["slot_g", "slot_b", "slot_anchor"],
        slots=[
            PlanSlot(id="slot_g", index=0, stage="greeting", kind="greeting", question_text="Hello!"),
            PlanSlot(id="slot_b", index=1, stage="background", kind="background", question_text="Tell me about yourself."),
            PlanSlot(
                id="slot_anchor",
                index=2,
                stage="technical",
                kind="anchor",
                skill_id="skill_cache",
                skill_name="Caching",
                question_text="How do you configure Redis Cluster for high availability?",
                variant_group="main",
            ),
            PlanSlot(
                id="slot_alt",
                index=3,
                stage="technical",
                kind="anchor_alt",
                skill_id="skill_cache",
                skill_name="Caching",
                question_text="Hypothetically, how would you design an in-memory cache from scratch?",
                variant_group="alt",
                parent_question_id="slot_anchor",
                is_required=False,
            ),
        ],
    )
    ordered_slots = plan.get_ordered_slots()
    # Normal progression must NOT include anchor_alt
    assert all(s.kind != "anchor_alt" for s in ordered_slots)

    # build_script() MUST include anchor_alt for indexing
    session_mock = MagicMock()
    session_mock.runtime_state = {"script_plan": plan.model_dump()}
    session_mock.questions = []
    script = build_script(session_mock)
    alt_in_script = next((q for q in script["questions"] if q["kind"] == "anchor_alt"), None)
    assert alt_in_script is not None
    assert alt_in_script["id"] == "slot_alt"

    # SessionStart indexes anchor_alt in skill_questions
    init_state = ConductorState(session_id="sess_alt")
    start_state, _ = step(init_state, SessionStart(session_id="sess_alt", plan=script, now_ms=1000))
    caching_sq = start_state.skill_questions.get("Caching", {})
    assert "anchor_alt" in caching_sq
    assert caching_sq["anchor_alt"].question_text == "Hypothetically, how would you design an in-memory cache from scratch?"

    # validate_and_apply_decision selects anchor_alt on no_experience=True
    caching_state = ConductorState(
        session_id="sess_alt_no_exp",
        phase=ConductorPhase.SKILL_ANCHOR,
        skill_names=["Caching"],
        current_skill_index=0,
        skill_questions=start_state.skill_questions,
        questions=start_state.questions,
        current_slot_id="slot_anchor",
        committed_answer="I haven't had the chance to work with Redis Cluster directly.",
    )
    decision = {
        "action": "follow_up",
        "ack": "No problem at all.",
        "no_experience": True,
    }
    applied_state, effects = validate_and_apply_decision(caching_state, decision, now_ms=2000)
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "Hypothetically, how would you design an in-memory cache from scratch?" in speak.text
    assert applied_state.current_slot_id == "slot_alt"


# =============================================================================
# 12. Generic Follow-up Fallback Removed
# =============================================================================

@pytest.mark.asyncio
async def test_empty_followup_question_never_speaks_generic_fallback():
    """Verify that an empty follow_up_question in plan mode falls back to unasked
    prepared probes or next planned question, and never speaks 'Could you elaborate on that approach?'.
    """
    plan = ScriptPlan(
        plan_id="plan_fol_test",
        application_id="app_fol",
        job_id="job_fol",
        input_hash="hash_fol",
        slots=[
            PlanSlot(
                id="slot_tech_1",
                index=1,
                stage="technical",
                kind="anchor",
                skill_id="skill_k8s",
                skill_name="Kubernetes",
                question_text="How do you manage pod disruption budgets?",
                followup_probes=["How does that interact with node draining?"],
            ),
            PlanSlot(
                id="slot_tech_2",
                index=2,
                stage="technical",
                kind="anchor",
                skill_id="skill_sec",
                skill_name="Security",
                question_text="How do you enforce mTLS between services?",
            ),
        ],
    )
    runner = SessionRunner(
        session_id="sess_fol_test",
        script={"script_plan": plan.model_dump(), "questions": []},
        llm_fn=None,
    )
    runner.state.phase = ConductorPhase.SKILL_ANCHOR
    runner.state.skill_names = ["Kubernetes", "Security"]
    runner.state.current_skill_index = 0
    runner.state.current_question_index = 1

    req = RequestDecision(
        token="tok_fol_empty",
        skill="Kubernetes",
        question_text="How do you manage pod disruption budgets?",
        answer_text="We set minAvailable to eighty percent.",
        followups_used=0,
        time_left_ms=180000,
    )

    empty_fol_selector = SelectorOutput(
        decision="FOLLOW_UP",
        follow_up_question="",
        ack="Got it.",
        bridge="Looking closer,",
    )

    with patch(
        "backend.app.services.interview_v2.runner.select_next_interview_action",
        new_callable=AsyncMock,
        return_value=(empty_fol_selector, {}),
    ):
        await runner._call_decision_llm(req)

    dec_msg = None
    while not runner.queue.empty():
        msg = runner.queue.get_nowait()
        if isinstance(msg, DecisionReady):
            dec_msg = msg

    assert dec_msg is not None
    assert dec_msg.decision["action"] == "follow_up"
    assert "elaborate on that approach" not in dec_msg.decision["question"].lower()
    assert dec_msg.decision["question"] == "How does that interact with node draining?"


# =============================================================================
# 13. Plan Input Hash Comprehensive Sensitivity
# =============================================================================

def test_compute_plan_input_hash_sensitivity():
    """Verify that compute_plan_input_hash is sensitive to all fields from
    to_generation_prompt_vars(), and deterministic for identical inputs.
    """
    ctx1 = HydratedInterviewContext(
        application_id="app_hash_1",
        job_id="job_hash_1",
        candidate_full_name="Jane Doe",
        candidate_first_name="Jane",
        department="Platform Engineering",
        interviewer_tone="Technical, direct, encouraging",
        fit_pitch="Passionate about cloud-native infrastructure and distributed systems.",
        resume_education=[{"degree": "B.S. Computer Science", "school": "MIT"}],
        resume_certifications=[{"name": "CKA"}],
        skills=[{
            "id": "s1",
            "name": "Kubernetes",
            "category": "Infrastructure",
            "target_level": "L4",
            "weight_percentage": 50,
            "priority_tier": "P0",
            "rubric_l1": "Basic container knowledge",
            "rubric_l2": "Deploys simple pods",
            "rubric_l3": "Configures stateful sets",
            "rubric_l4": "Designs multi-cluster topologies",
            "rubric_l5": "Writes custom operators",
        }],
    )

    hash1 = compute_plan_input_hash(ctx1, "prompt_v2")

    # 1. Deterministic
    assert compute_plan_input_hash(ctx1, "prompt_v2") == hash1

    # 2. department change
    ctx_dept = HydratedInterviewContext(**{**ctx1.__dict__, "department": "Data Engineering"})
    assert compute_plan_input_hash(ctx_dept, "prompt_v2") != hash1

    # 3. interviewer_tone change
    ctx_tone = HydratedInterviewContext(**{**ctx1.__dict__, "interviewer_tone": "Warm, conversational, academic"})
    assert compute_plan_input_hash(ctx_tone, "prompt_v2") != hash1

    # 4. fit_pitch change
    ctx_pitch = HydratedInterviewContext(**{**ctx1.__dict__, "fit_pitch": "Experienced with machine learning platforms."})
    assert compute_plan_input_hash(ctx_pitch, "prompt_v2") != hash1

    # 5. resume_education change
    ctx_edu = HydratedInterviewContext(**{**ctx1.__dict__, "resume_education": [{"degree": "M.S. Robotics", "school": "Stanford"}]})
    assert compute_plan_input_hash(ctx_edu, "prompt_v2") != hash1

    # 6. resume_certifications change
    ctx_cert = HydratedInterviewContext(**{**ctx1.__dict__, "resume_certifications": [{"name": "AWS Solutions Architect"}]})
    assert compute_plan_input_hash(ctx_cert, "prompt_v2") != hash1

    # 7. skill category change
    s_cat = dict(ctx1.skills[0], category="Architecture")
    ctx_cat = HydratedInterviewContext(**{**ctx1.__dict__, "skills": [s_cat]})
    assert compute_plan_input_hash(ctx_cat, "prompt_v2") != hash1

    # 8. skill target_level change
    s_lvl = dict(ctx1.skills[0], target_level="L5")
    ctx_lvl = HydratedInterviewContext(**{**ctx1.__dict__, "skills": [s_lvl]})
    assert compute_plan_input_hash(ctx_lvl, "prompt_v2") != hash1


# =============================================================================
# 14. In-Progress Session Sync Protection
# =============================================================================

@pytest.mark.asyncio
async def test_in_progress_session_sync_protection():
    """Verify that _sync_plan_to_session never modifies runtime_state['script_plan']
    for sessions that are in_progress or completed.
    """
    from backend.app.services.interview_v2.plan_writer import _sync_plan_to_session

    initial_plan = {"plan_id": "original_plan_id", "slots": []}
    session = InterviewSession(
        id="sess_sync_prot",
        status="in_progress",
        runtime_state={"script_plan": initial_plan},
    )

    new_plan = ScriptPlan(
        plan_id="replacement_plan_id",
        application_id="app_sync",
        job_id="job_sync",
        input_hash="hash_sync",
        slots=[],
    )

    db_mock = AsyncMock()
    await _sync_plan_to_session(db_mock, session, new_plan)

    # Must preserve original plan untouched
    assert session.runtime_state["script_plan"]["plan_id"] == "original_plan_id"


# =============================================================================
# 15. REST GET re-selects synchronized plan questions
# =============================================================================

@pytest.mark.asyncio
async def test_get_application_interview_session_returns_synchronized_questions():
    """GET must return question rows created during plan ensure, not a stale empty relationship."""
    import httpx
    from backend.app.main import app as fastapi_app
    from backend.app.services.auth import create_access_token

    async with AsyncSessionLocal() as db:
        recruiter = User(
            id=str(uuid.uuid4()),
            email=f"recruiter_get_{uuid.uuid4().hex[:6]}@example.com",
            full_name="Recruiter GET",
            password_hash="fake",
            role="recruiter",
        )
        candidate = User(
            id=str(uuid.uuid4()),
            email=f"candidate_get_{uuid.uuid4().hex[:6]}@example.com",
            full_name="Candidate GET",
            password_hash="fake",
            role="candidate",
        )
        db.add_all([recruiter, candidate])
        await db.flush()

        job = JobPosting(
            id=str(uuid.uuid4()),
            job_title="Platform Engineer",
            department="Engineering",
            recruiter_id=recruiter.id,
            status="active",
        )
        db.add(job)
        await db.flush()

        blueprint = InterviewBlueprint(
            id=str(uuid.uuid4()),
            job_id=job.id,
            version=1,
            status="approved",
            total_duration_mins=20,
            active_skill_mins=14.0,
            fixed_overhead_mins=6.0,
        )
        db.add(blueprint)
        await db.flush()
        job.active_blueprint_id = blueprint.id
        await db.flush()

        application = JobApplication(
            id=str(uuid.uuid4()),
            job_id=job.id,
            candidate_id=candidate.id,
            full_name=candidate.full_name,
            email=candidate.email,
            status="scheduled",
        )
        db.add(application)
        await db.flush()

        plan = ScriptPlan(
            plan_id="plan_get_sync",
            application_id=application.id,
            job_id=job.id,
            input_hash="hash_get_sync",
            slots=[
                PlanSlot(id="slot_get_greet", index=0, stage="greeting", kind="greeting", question_text="Hello!"),
                PlanSlot(id="slot_get_anchor", index=1, stage="technical", kind="anchor", question_text="How do you debug production latency?"),
            ],
        )
        session = InterviewSession(
            id=str(uuid.uuid4()),
            application_id=application.id,
            job_id=job.id,
            status="scheduled",
            duration_planned_mins=20,
            runtime_state={"script_plan": plan.model_dump()},
        )
        db.add(session)
        await db.commit()
        application_id = application.id
        candidate_id = candidate.id
        candidate_email = candidate.email

    token = create_access_token({"sub": candidate_id, "email": candidate_email, "role": "candidate", "id": candidate_id})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://test") as client:
        response = await client.get(
            f"/api/applications/{application_id}/interview-session",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    payload = response.json()
    returned_ids = {q["id"] for q in payload["questions"]}
    assert {"slot_get_greet", "slot_get_anchor"}.issubset(returned_ids)


# =============================================================================
# 16. Hypothetical raw action selects exact anchor_alt
# =============================================================================

def test_hypothetical_raw_action_selects_anchor_alt_without_no_experience_flag():
    """A raw action of 'hypothetical' must select the stored anchor_alt even when
    no_experience is false, and must never speak an empty question.
    """
    plan = ScriptPlan(
        plan_id="plan_hypothetical_raw",
        application_id="app_hyp",
        job_id="job_hyp",
        input_hash="hash_hyp",
        question_order=["slot_h_g", "slot_h_b", "slot_h_anchor"],
        slots=[
            PlanSlot(id="slot_h_g", index=0, stage="greeting", kind="greeting", question_text="Hello!"),
            PlanSlot(id="slot_h_b", index=1, stage="background", kind="background", question_text="Tell me about yourself."),
            PlanSlot(
                id="slot_h_anchor",
                index=2,
                stage="technical",
                kind="anchor",
                skill_id="skill_cache",
                skill_name="Caching",
                question_text="How do you configure Redis Cluster for high availability?",
            ),
            PlanSlot(
                id="slot_h_alt",
                index=3,
                stage="technical",
                kind="anchor_alt",
                skill_id="skill_cache",
                skill_name="Caching",
                question_text="Hypothetically, how would you design an in-memory cache from scratch?",
                parent_question_id="slot_h_anchor",
                is_required=False,
            ),
        ],
    )
    session_mock = MagicMock()
    session_mock.runtime_state = {"script_plan": plan.model_dump()}
    session_mock.questions = []
    script = build_script(session_mock)
    start_state, _ = step(ConductorState(session_id="sess_hyp"), SessionStart(session_id="sess_hyp", plan=script, now_ms=1000))

    state = ConductorState(
        session_id="sess_hyp",
        phase=ConductorPhase.SKILL_ANCHOR,
        skill_names=["Caching"],
        current_skill_index=0,
        skill_questions=start_state.skill_questions,
        questions=start_state.questions,
        current_slot_id="slot_h_anchor",
        committed_answer="I have not worked with Redis Cluster directly.",
    )
    new_state, effects = validate_and_apply_decision(
        state,
        {"action": "hypothetical", "no_experience": False},
        now_ms=2000,
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert speak.question_text == "Hypothetically, how would you design an in-memory cache from scratch?"
    assert speak.text.strip() != ""
    assert "Hypothetically, how would you design an in-memory cache from scratch?" in speak.text
    assert new_state.current_slot_id == "slot_h_alt"
    assert new_state.current_question_index == 3


def test_hypothetical_without_alt_uses_non_empty_anchor_fallback():
    """When no anchor_alt/escalation/probe exists, hypothetical must fall back to a
    non-empty stored question rather than speaking an empty string.
    """
    plan = ScriptPlan(
        plan_id="plan_hypothetical_fallback",
        application_id="app_hyp2",
        job_id="job_hyp2",
        input_hash="hash_hyp2",
        question_order=["slot_f_g", "slot_f_anchor"],
        slots=[
            PlanSlot(id="slot_f_g", index=0, stage="greeting", kind="greeting", question_text="Hello!"),
            PlanSlot(
                id="slot_f_anchor",
                index=1,
                stage="technical",
                kind="anchor",
                skill_id="skill_py",
                skill_name="Python",
                question_text="How do you profile a slow Python service?",
            ),
        ],
    )
    session_mock = MagicMock()
    session_mock.runtime_state = {"script_plan": plan.model_dump()}
    session_mock.questions = []
    script = build_script(session_mock)
    start_state, _ = step(ConductorState(session_id="sess_hyp2"), SessionStart(session_id="sess_hyp2", plan=script, now_ms=1000))

    state = ConductorState(
        session_id="sess_hyp2",
        phase=ConductorPhase.SKILL_ANCHOR,
        skill_names=["Python"],
        current_skill_index=0,
        skill_questions=start_state.skill_questions,
        questions=start_state.questions,
        current_slot_id="slot_f_anchor",
        committed_answer="I have not profiled a Python service before.",
    )
    new_state, effects = validate_and_apply_decision(
        state,
        {"action": "hypothetical", "no_experience": False},
        now_ms=2000,
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert speak.question_text.strip() != ""
    assert speak.text.strip() != ""
    assert new_state.current_slot_id == "slot_f_anchor"


# =============================================================================
# 17. Streaming Q&A ack suppression on deferral
# =============================================================================

@pytest.mark.asyncio
async def test_candidate_qa_deferral_emits_no_ack_even_if_streamed_early():
    """A streaming ack emitted before the final decision must not survive a deferral."""
    job_record = {
        "title": "Lead Platform Engineer",
        "description": "We run distributed microservices using Go.",
        "skills": ["Go"],
    }
    runner = SessionRunner(
        session_id="sess_qa_stream_deferral",
        script={"job_record": job_record, "questions": []},
        llm_fn=None,
    )
    req = RequestDecision(
        token="tok_qa_stream_deferral",
        skill="Candidate Q&A",
        question_text="Do you have any questions for me?",
        answer_text="What is the base salary and equity compensation for this role?",
    )
    llm_return = {
        "ack": "You are asking about the details for this role.",
        "answer": "The compensation is $200,000 base with equity. Anything else?",
        "source_facts": ["job_title"],
    }

    async def fake_stream(**kwargs):
        on_ack = kwargs.get("on_ack_ready")
        if on_ack:
            on_ack({"action": "candidate_qa", "ack": "You are asking about the details for this role."})
        return llm_return, {"ttft_ms": 90}

    with patch(
        "backend.app.services.interview_v2.runner.stream_decision_with_ack_first",
        side_effect=fake_stream,
    ):
        await runner._call_decision_llm(req)

    dec_msg = None
    ack_msg = None
    while not runner.queue.empty():
        msg = runner.queue.get_nowait()
        if isinstance(msg, DecisionReady):
            dec_msg = msg
        elif isinstance(msg, AckReady):
            ack_msg = msg

    assert dec_msg is not None
    assert dec_msg.decision["question"] == APPROVED_QA_DEFERRAL
    assert dec_msg.decision["ack"] == ""
    assert ack_msg is None


@pytest.mark.asyncio
async def test_candidate_qa_llm_fn_uses_prompt_keywords_first():
    """Q&A llm_fn must receive the rendered QA prompts, not positional question text."""
    captured: Dict[str, Any] = {}

    def qa_llm(system_prompt: str, user_prompt: str):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return {
            "ack": "You are asking about the primary database.",
            "answer": "We run PostgreSQL for primary transactional datastores. Anything else?",
            "source_facts": ["description_fact_001"],
        }

    job_record = {
        "title": "Lead Platform Engineer",
        "description": "We run distributed microservices using PostgreSQL on Google Cloud Platform.",
        "skills": ["PostgreSQL"],
    }
    runner = SessionRunner(
        session_id="sess_qa_prompt_kwargs",
        script={"job_record": job_record, "questions": []},
        llm_fn=qa_llm,
    )
    req = RequestDecision(
        token="tok_qa_prompt_kwargs",
        skill="Candidate Q&A",
        question_text="Do you have any questions for me?",
        answer_text="What database do you run in production?",
    )
    await runner._call_decision_llm(req)

    assert "system_prompt" in captured and "user_prompt" in captured
    assert "What database do you run in production?" in captured["user_prompt"]
    assert "candidate_qa_system" not in captured["system_prompt"]
    assert "JSON" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_candidate_qa_llm_fn_legacy_positional_signature_still_supported():
    """Legacy three-argument test doubles must still work when keyword prompts are unsupported."""
    def legacy_llm(question: str, answer: str, escalation: str):
        return {
            "ack": "You are asking about the primary database.",
            "answer": "We run PostgreSQL for primary transactional datastores. Anything else?",
            "source_facts": ["description_fact_001"],
        }

    job_record = {
        "title": "Lead Platform Engineer",
        "description": "We run distributed microservices using PostgreSQL on Google Cloud Platform.",
        "skills": ["PostgreSQL"],
    }
    runner = SessionRunner(
        session_id="sess_qa_prompt_legacy",
        script={"job_record": job_record, "questions": []},
        llm_fn=legacy_llm,
    )
    req = RequestDecision(
        token="tok_qa_prompt_legacy",
        skill="Candidate Q&A",
        question_text="Do you have any questions for me?",
        answer_text="What database do you run in production?",
    )
    await runner._call_decision_llm(req)

    dec_msg = None
    while not runner.queue.empty():
        msg = runner.queue.get_nowait()
        if isinstance(msg, DecisionReady):
            dec_msg = msg
    assert dec_msg is not None
    assert dec_msg.decision["action"] == "candidate_qa"
    assert "PostgreSQL" in dec_msg.decision["question"]


@pytest.mark.asyncio
async def test_selector_level_candidate_qa_deferral_discards_streamed_ack():
    """A selector-level CANDIDATE_QA decision must not leak a streaming ack when the
    final validated reply is a deferral.
    """
    plan = ScriptPlan(
        plan_id="plan_selector_qa_deferral",
        application_id="app_sel_qa",
        job_id="job_sel_qa",
        input_hash="hash_sel_qa",
        slots=[
            PlanSlot(id="slot_sel_anchor", index=0, stage="technical", kind="anchor", skill_name="Python", question_text="How do you manage memory in Python?"),
        ],
    )
    script = {
        "job_record": {"title": "Engineer", "description": "We build Python services.", "skills": ["Python"]},
        "questions": [],
        "script_plan": plan.model_dump(),
    }
    runner = SessionRunner("sess_selector_qa_deferral", script, llm_fn=None)
    req = RequestDecision(
        token="tok_sel_qa_deferral",
        skill="Python",
        question_text="How do you manage memory in Python?",
        answer_text="What is the base salary and equity compensation for this role?",
    )

    def fake_selector(selector_input, llm_fn=None, on_stream_ack=None):
        if on_stream_ack:
            on_stream_ack({"decision": "CANDIDATE_QA", "ack": "You are asking about the details for this role."})
        return SelectorOutput(decision="CANDIDATE_QA", reason_code="candidate_question"), {}

    deferral = {
        "ack": "You are asking about the details for this role.",
        "answer": "The compensation is $200,000 base with equity. Anything else?",
        "source_facts": ["job_title"],
    }
    with patch(
        "backend.app.services.interview_v2.runner.select_next_interview_action",
        side_effect=fake_selector,
    ), patch(
        "backend.app.services.interview_v2.runner.stream_decision_with_ack_first",
        new_callable=AsyncMock,
        return_value=(deferral, {"ttft_ms": 80}),
    ):
        await runner._call_decision_llm(req)

    dec_msg = None
    ack_msg = None
    while not runner.queue.empty():
        msg = runner.queue.get_nowait()
        if isinstance(msg, DecisionReady):
            dec_msg = msg
        elif isinstance(msg, AckReady):
            ack_msg = msg

    assert dec_msg is not None
    assert dec_msg.decision["action"] == "candidate_qa"
    assert dec_msg.decision["question"] == APPROVED_QA_DEFERRAL
    assert dec_msg.decision["ack"] == ""
    assert ack_msg is None


def test_intro_decision_speaks_stored_anchor_not_model_authored_question():
    """After the intro answer, a model-authored question must never replace the
    prepared first-skill anchor from the script plan.
    """
    plan = ScriptPlan(
        plan_id="plan_intro_anchor",
        application_id="app_intro",
        job_id="job_intro",
        input_hash="hash_intro",
        question_order=["slot_i_g", "slot_i_b", "slot_i_anchor"],
        slots=[
            PlanSlot(id="slot_i_g", index=0, stage="greeting", kind="greeting", question_text="Hello!"),
            PlanSlot(id="slot_i_b", index=1, stage="background", kind="background", question_text="Tell me about your background."),
            PlanSlot(
                id="slot_i_anchor",
                index=2,
                stage="technical",
                kind="anchor",
                skill_id="skill_cache",
                skill_name="Caching",
                question_text="How do you configure Redis Cluster for high availability?",
            ),
        ],
    )
    session_mock = MagicMock()
    session_mock.runtime_state = {"script_plan": plan.model_dump()}
    session_mock.questions = []
    script = build_script(session_mock)
    start_state, _ = step(ConductorState(session_id="sess_intro"), SessionStart(session_id="sess_intro", plan=script, now_ms=1000))

    state = ConductorState(
        session_id="sess_intro",
        phase=ConductorPhase.INTRO,
        phase_before_commit=ConductorPhase.INTRO,
        skill_names=start_state.skill_names,
        current_skill_index=0,
        skill_questions=start_state.skill_questions,
        questions=start_state.questions,
        current_slot_id="slot_i_b",
        current_question_index=1,
        committed_answer="I have built caches for several years.",
    )
    new_state, effects = validate_and_apply_decision(
        state,
        {
            "action": "follow_up",
            "ack": "Thanks for sharing that.",
            "question": "Which cache eviction policy do you prefer?",
            "target_skill": "Unrelated Skill",
        },
        now_ms=2000,
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    anchor_text = "How do you configure Redis Cluster for high availability?"
    assert anchor_text in speak.question_text
    assert anchor_text in speak.text
    assert "Which cache eviction policy" not in speak.text
    assert new_state.current_slot_id == "slot_i_anchor"
    assert new_state.current_question_index == 2
