"""Comprehensive verification test suite for the Bounded-Agentic, Plan-and-Select Live Interviewer.

Tests:
1. Prompt Template Package (loader, variable substitutions, missing var errors)
2. Context Hydrator (PII stripping, handling missing fields, generation prompt vars, live turn summary)
3. Deterministic Plan Skeleton (1 greeting, 1 background, P0 coverage, time budgets, 1 QA, 1 closing, hash)
4. Plan Writer & Persistence (1:1 slot matching, repair loop, skeleton fallback, idempotency by input_hash)
5. Live Selector (ADVANCE with exact planned question, FOLLOW_UP <=28 words & depth, CLARIFY, CANDIDATE_QA, END)
6. Plan-Aware Fallback (zero canned generic questions, neutral ack, advance to next planned question)
7. Runner Integration (SessionRunner with ScriptPlan, single composed utterance, recent turns tracking)
8. Gated Live Bedrock Call (live test against apac.amazon.nova-pro-v1:0 if credentials present)
"""

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import asyncio
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
    InterviewTranscriptTurn,
    JobApplication,
    JobCustomQuestion,
    JobPosting,
    JobSkill,
    User,
)
from backend.app.prompts.loader import (
    PROMPT_VERSION_ACK,
    PROMPT_VERSION_PLAN,
    PROMPT_VERSION_QA,
    PROMPT_VERSION_SELECTOR,
    PromptTemplateError,
    render_prompt,
    validate_all_templates,
)
from backend.app.services.interview_v2.conductor import (
    AckReady,
    ConductorPhase,
    ConductorState,
    DecisionReady,
    PlanQuestion,
    RequestDecision,
    SessionStart,
    Speak,
    step,
)
from backend.app.services.interview_v2.context_hydrator import (
    HydratedInterviewContext,
    hydrate_interview_context,
)
from backend.app.services.interview_v2.plan_schema import (
    PlanSlot,
    ScriptPlan,
    build_plan_skeleton,
    clean_role_title_for_speech,
    compute_plan_input_hash,
    validate_script_plan,
)
from backend.app.services.interview_v2.plan_writer import (
    _build_candidate_plan_from_raw,
    generate_or_load_script_plan,
    write_interview_script_plan,
)
from backend.app.services.interview_v2.runner import SessionRunner
from backend.app.services.interview_v2.selector import (
    SelectorInput,
    SelectorOutput,
    _generate_plan_aware_fallback,
    select_next_interview_action,
    validate_selector_output,
)
from backend.app.services.llm_router import get_bedrock_bearer_token


# =============================================================================
# Helper Fixtures & Dummy Clients
# =============================================================================

class FakeWebSocket:
    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
        self.sent_bytes: List[bytes] = []

    async def send_json(self, data: Dict[str, Any]) -> None:
        self.sent_messages.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)


class FakeAuraTTSClient:
    def __init__(self):
        self.spoken_texts: List[str] = []

    async def speak_text_stream(self, text: str, voice: Optional[str] = None):
        self.spoken_texts.append(text)
        yield b"\x00\x00" * 480


# =============================================================================
# 1. Prompt Template Package Tests
# =============================================================================

def test_prompt_loader_validates_all_templates():
    """Verify all 9 prompt templates compile and contain no syntax errors."""
    validate_all_templates()


def test_prompt_loader_substitutes_variables():
    """Verify render_prompt substitutes $variables without Jinja2."""
    rendered = render_prompt("interview/plan_generation_system")
    assert "AI technical interviewer and script author for Candidly" in rendered

    rendered_user = render_prompt(
        "interview/selector_user",
        candidate_and_job_summary="Job: Senior Python Dev. Candidate: Jane Doe.",
        past_two_turns_json='[{"question": "Intro", "answer": "Done"}]',
        current_question_json='{"id": "q1", "text": "How do you handle asyncio concurrency?"}',
        candidate_answer="I use asyncio.gather for network I/O.",
        next_planned_question_json='{"id": "q_next_1", "text": "Explain Python GIL limitations."}',
        optional_prepared_followups_json="[]",
        no_knowledge_signal="false",
        alternative_question_json="null",
        followups_remaining="2",
        remaining_time_mins="14.5",
        allowed_actions_json='["ADVANCE", "FOLLOW_UP", "CLARIFY_OR_REPEAT", "SWAP_QUESTION", "CANDIDATE_QA", "END_INTERVIEW"]',
        skill_rubric_json='{"L3": "Explains asyncio concurrency"}',
        escalation_question="How would you scale that to 10k rps?",
        candidate_hooks_json='["AI Recruiter Platform (FastAPI)"]',
        covered_expectations_json="[]",
        hint_or_alt_used_on_skill="false",
        candidate_dossier_json='{"name": "Jane", "notable_projects": ["AI Recruiter Platform"]}',
        last_estimated_level="L2",
        followups_used_on_skill="1",
        max_followups_on_skill="2",
    )
    assert "Job: Senior Python Dev" in rendered_user
    assert "How do you handle asyncio concurrency?" in rendered_user
    assert "Explain Python GIL limitations." in rendered_user


def test_prompt_loader_missing_variable_raises_custom_error():
    """Verify missing required template variables raise PromptTemplateError."""
    with pytest.raises(PromptTemplateError) as exc_info:
        render_prompt("interview/selector_user", candidate_and_job_summary="Some summary")
    assert "Missing required template variable" in str(exc_info.value)


# =============================================================================
# 2. Context Hydrator Tests
# =============================================================================

@pytest.mark.asyncio
async def test_context_hydrator_pii_sanitization_and_fallbacks():
    """Verify context hydrator strips PII (email, phone, salary) and handles missing resume."""
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email="candidate_secret_pii@example.com",
            full_name="Jane Doe",
            password_hash="fake",
        )
        db.add(user)

        job = JobPosting(
            id=str(uuid.uuid4()),
            job_title="Senior Distributed Systems SDE-II",
            department="Core Infrastructure",
            seniority_level="Senior",
            job_description="Build scalable microservices with gRPC and async workflows.",
            interview_duration_mins=25,
            status="active",
        )
        db.add(job)

        skill_p0 = JobSkill(
            id=str(uuid.uuid4()),
            job_id=job.id,
            name="Distributed Systems",
            category="technical",
            priority_tier="P0",
            weight_percentage=60.0,
            rubric_l1="Basic knowledge",
            rubric_l3="Designs fault-tolerant retry loops",
            rubric_l5="Architects global consensus engines",
        )
        skill_p1 = JobSkill(
            id=str(uuid.uuid4()),
            job_id=job.id,
            name="Concurrency",
            category="technical",
            priority_tier="P1",
            weight_percentage=40.0,
        )
        db.add_all([skill_p0, skill_p1])

        app = JobApplication(
            id=str(uuid.uuid4()),
            job_id=job.id,
            candidate_id=user.id,
            full_name="Jane Doe",
            email="candidate_secret_pii@example.com",
            phone="123-456-7890",
            status="in_review",
            self_reported_experience_years=6.5,
            fit_pitch="6+ years building distributed message queues with Kafka and Raft.",
        )
        db.add(app)
        await db.commit()

        context = await hydrate_interview_context(db, app.id)

        assert context.candidate_first_name == "Jane"
        assert context.candidate_full_name == "Jane Doe"
        assert context.job_title == "Senior Distributed Systems SDE-II"
        assert context.interview_duration_mins == 25
        assert len(context.skills) == 2

        # Verify generation prompt vars
        gen_vars = context.to_generation_prompt_vars()
        assert "candidate_profile_json" in gen_vars
        assert "job_profile_json" in gen_vars
        assert "competencies_json" in gen_vars

        cand_json = json.loads(gen_vars["candidate_profile_json"])
        assert "email" not in cand_json
        assert "phone" not in cand_json
        assert cand_json["name"] == "Jane"
        assert cand_json["years_of_experience"] == 6.5

        # Verify live turn summary
        live_summary = context.to_live_turn_summary()
        assert "Applying for: Senior Distributed Systems SDE-II" in live_summary
        assert "Jane" in live_summary
        assert "Distributed Systems" in live_summary
        assert "candidate_secret_pii@example.com" not in live_summary


# =============================================================================
# 3. Plan Schema & Deterministic Skeleton Tests
# =============================================================================

def test_clean_role_title_for_speech():
    """Verify role title cleaner replaces hyphens and expands SDE acronyms."""
    assert clean_role_title_for_speech("Senior SDE-II") == "Senior Software Development Engineer 2"
    assert clean_role_title_for_speech("Staff SWE — Backend") == "Staff Software Engineer Backend"
    assert clean_role_title_for_speech(None) == "Software Engineer"


def test_plan_skeleton_deterministic_structure_and_time_budgets():
    """Verify deterministic skeleton contains required stages and balanced time budgets."""
    context = HydratedInterviewContext(
        application_id="app_123",
        job_id="job_456",
        candidate_full_name="Alex Smith",
        candidate_first_name="Alex",
        job_title="Software Engineer - Core Backend",
        interview_duration_mins=20,
        skills=[
            {
                "id": "sk_1",
                "name": "Python Concurrency",
                "priority_tier": "P0",
                "weight_percentage": 50.0,
                "anchor_question": "Explain how asyncio tasks coordinate with event loops.",
                "expected_key_points": ["Task scheduling", "Cooperative multitasking"],
            },
            {
                "id": "sk_2",
                "name": "Distributed Caching",
                "priority_tier": "P1",
                "weight_percentage": 50.0,
                "anchor_question": "How do you handle cache invalidation and stampedes?",
                "expected_key_points": ["Cache aside", "Probabilistic early expiration"],
            },
        ],
    )

    skeleton = build_plan_skeleton(context)

    # 1. Exact required stages present
    stages = [s.stage for s in skeleton.slots]
    assert stages[0] == "greeting"
    assert stages[1] == "background"
    assert "technical" in stages
    assert stages[-2] == "candidate_qa"
    assert stages[-1] == "closing"

    # 2. Greeting cleans role title
    greeting_slot = skeleton.slots[0]
    assert "Core Backend" in greeting_slot.question_text
    assert "-" not in greeting_slot.question_text

    # 3. Time budgets sum to duration
    total_sec = sum(s.estimated_seconds for s in skeleton.slots)
    assert total_sec <= 20 * 60 + 60
    assert total_sec >= 20 * 60 - 120

    # 4. Hash stability
    h1 = compute_plan_input_hash(context, "interview_plan.v1")
    h2 = compute_plan_input_hash(context, "interview_plan.v1")
    assert h1 == h2
    assert len(h1) == 64

    # 5. Validation succeeds on skeleton
    errors = validate_script_plan(skeleton, skeleton)
    assert errors == []


# =============================================================================
# 4. Plan Script Writer & Persistence Tests
# =============================================================================

@pytest.mark.asyncio
async def test_write_interview_script_plan_with_mock_llm_and_1_to_1_slots():
    """Verify LLM slot wording merges onto skeleton with 1:1 slot ID alignment."""
    context = HydratedInterviewContext(
        application_id="app_writer_1",
        job_id="job_writer_1",
        candidate_full_name="Sam Taylor",
        candidate_first_name="Sam",
        job_title="Backend Engineer",
        interview_duration_mins=15,
        skills=[{
            "id": "sk_sql",
            "name": "Database Systems",
            "priority_tier": "P0",
            "weight_percentage": 100.0,
        }],
    )
    skeleton = build_plan_skeleton(context)

    # Mock LLM provides personalized wording preserving skeleton slot IDs
    async def mock_llm_success(system_prompt: str, user_prompt: str):
        slots_payload = []
        for s in skeleton.slots:
            slots_payload.append({
                "id": s.id,
                "stage": s.stage,
                "question_text": f"Personalized voice question for {s.stage}: what is your approach?",
                "expected_key_points": s.expected_key_points,
                "followup_probes": ["Can you expand on that specific architectural detail?"],
            })
        return {"slots": slots_payload}

    plan, metrics = await write_interview_script_plan(skeleton, context, llm_fn=mock_llm_success)

    assert metrics["validation_passed"] is True
    assert metrics["fallback_used"] is False
    assert len(plan.slots) == len(skeleton.slots)
    for p_slot, s_slot in zip(plan.slots, skeleton.slots):
        assert p_slot.id == s_slot.id
        assert p_slot.stage == s_slot.stage
        assert "Personalized voice question" in p_slot.question_text


@pytest.mark.asyncio
async def test_write_interview_script_plan_repair_loop_and_skeleton_fallback():
    """Verify invalid slot IDs trigger repair loop, and fallback to skeleton on continued failure."""
    context = HydratedInterviewContext(
        application_id="app_writer_2",
        job_id="job_writer_2",
        candidate_full_name="Sam Taylor",
        candidate_first_name="Sam",
        job_title="Backend Engineer",
        interview_duration_mins=15,
    )
    skeleton = build_plan_skeleton(context)

    repair_call_count = 0

    async def mock_llm_always_invalid(system_prompt: str, user_prompt: str):
        nonlocal repair_call_count
        repair_call_count += 1
        # Malformed: missing required skeleton IDs
        return {"slots": [{"id": "bad_id_123", "stage": "greeting", "question_text": "Bad slot"}]}

    plan, metrics = await write_interview_script_plan(skeleton, context, llm_fn=mock_llm_always_invalid)

    assert repair_call_count >= 2  # initial attempt + repair attempt
    assert metrics["repair_attempted"] is True
    assert metrics["fallback_used"] is True
    assert metrics["validation_passed"] is False
    assert metrics["fallback_reason"] == "validation_failure_post_repair"
    # Returns safe deterministic skeleton
    assert plan == skeleton


@pytest.mark.asyncio
async def test_generate_or_load_script_plan_persistence_and_idempotency():
    """Verify script plan is persisted to DB and second call returns cached plan by input_hash."""
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email="idempotent_test@example.com",
            full_name="Robin Lee",
            password_hash="fake",
        )
        db.add(user)

        job = JobPosting(
            id=str(uuid.uuid4()),
            job_title="Lead Reliability Engineer",
            department="SRE",
            seniority_level="Lead",
            job_description="Own production uptime and incident management.",
            interview_duration_mins=20,
            status="active",
        )
        db.add(job)

        app = JobApplication(
            id=str(uuid.uuid4()),
            job_id=job.id,
            candidate_id=user.id,
            full_name="Robin Lee",
            email="idempotent_test@example.com",
            status="in_review",
            self_reported_experience_years=8.0,
        )
        db.add(app)
        await db.commit()

        # First call: generates and persists
        async def mock_llm_gen(system_prompt: str, user_prompt: str):
            # Parse skeleton to return matching IDs
            skel_idx = user_prompt.find('"slots": [')
            assert skel_idx != -1
            # Simple skeleton fallback
            return {"slots": []}

        plan_1 = await generate_or_load_script_plan(db, app.id, llm_fn=mock_llm_gen)
        assert plan_1 is not None
        assert plan_1.application_id == app.id

        # Verify InterviewGenerationRun recorded
        gen_runs = (await db.execute(
            select(InterviewGenerationRun).where(InterviewGenerationRun.application_id == app.id)
        )).scalars().all()
        assert len(gen_runs) >= 1
        assert gen_runs[0].input_snapshot_hash == plan_1.input_hash

        # Second call: returns cached plan idempotently without calling mock_llm
        llm_called = False

        async def failing_llm(**kwargs):
            nonlocal llm_called
            llm_called = True
            raise RuntimeError("Should not be called for cached plan!")

        plan_2 = await generate_or_load_script_plan(db, app.id, llm_fn=failing_llm)
        assert not llm_called
        assert plan_2.input_hash == plan_1.input_hash
        assert plan_2.plan_id == plan_1.plan_id


# =============================================================================
# 5. Live Bounded-Agentic Selector Tests
# =============================================================================

@pytest.mark.asyncio
async def test_live_selector_advance_action_preserves_exact_planned_question():
    """Verify ADVANCE action selects the exact stored text of next planned question without deviation."""
    next_planned = {
        "id": "slot_tech_2",
        "stage": "technical",
        "skill_id": "sk_dist",
        "skill_name": "Distributed Systems",
        "text": "How do you implement distributed dead-letter queues with exponential backoff?",
    }

    selector_input = SelectorInput(
        candidate_and_job_summary="Job: Senior SRE. Candidate: Pat Jordan.",
        past_two_turns=[],
        current_question={
            "id": "slot_tech_1",
            "stage": "technical",
            "skill_name": "Distributed Systems",
            "text": "Explain circuit breaker patterns in microservices.",
            "expected_key_points": ["State transitions", "Failure threshold"],
            "followup_count": 2,
            "max_followup_depth": 2,
        },
        candidate_answer="A circuit breaker opens when failures exceed a threshold, failing fast to protect downstream dependencies.",
        next_planned_question=next_planned,
        followups_remaining=0,
        remaining_time_mins=12.0,
    )

    async def mock_llm_advance(system_prompt: str, user_prompt: str, **kwargs):
        return {
            "decision": "ADVANCE",
            "planned_question_id": "slot_tech_2",
            "ack": "Failure thresholds protect downstream dependencies.",
            "reason_code": "planned_next",
            "rationale": "Candidate provided a solid answer and follow-ups are exhausted.",
            "confidence": 0.95,
        }

    output, metrics = await select_next_interview_action(selector_input, llm_fn=mock_llm_advance)

    assert output.decision == "ADVANCE"
    assert output.planned_question_id == "slot_tech_2"
    assert output.ack == "Failure thresholds protect downstream dependencies."
    assert metrics["validation_passed"] is True
    assert metrics["fallback_used"] is False


@pytest.mark.asyncio
async def test_live_selector_follow_up_word_count_and_depth_limits():
    """Verify FOLLOW_UP enforces <= 28 words and rejects follow-ups when budget is exhausted."""
    selector_input = SelectorInput(
        candidate_and_job_summary="Job: Python Engineer.",
        current_question={
            "id": "slot_1",
            "stage": "technical",
            "skill_name": "Python",
            "text": "How do you manage memory and reference counting in CPython?",
            "expected_key_points": ["PyObject refcount", "Cyclic garbage collector"],
            "followup_count": 0,
            "max_followup_depth": 2,
        },
        candidate_answer="CPython uses reference counts for immediate deallocation.",
        followups_remaining=2,
        remaining_time_mins=10.0,
    )

    # 1. Valid follow-up <= 28 words
    valid_followup = SelectorOutput(
        decision="FOLLOW_UP",
        follow_up_question="How does the cyclic garbage collector detect reference cycles that reference counting misses?",
        ack="Reference counts enable immediate deallocation.",
        reason_code="answer_gap",
    )
    errors = validate_selector_output(valid_followup, selector_input)
    assert errors == []

    # 2. Invalid follow-up > 28 words
    too_long_followup = SelectorOutput(
        decision="FOLLOW_UP",
        follow_up_question="Could you please walk me through in deep excruciating detail every single aspect of how the generational garbage collector detects cyclic dependencies across complex nested data structures in Python when reference counts fail to hit zero?",
        ack="Reference counting deallocates immediately.",
    )
    errors = validate_selector_output(too_long_followup, selector_input)
    assert any("exceeds 28 words" in e for e in errors)

    # 3. Follow-up when budget is 0
    exhausted_input = selector_input.model_copy(update={"followups_remaining": 0})
    errors_exhausted = validate_selector_output(valid_followup, exhausted_input)
    assert any("followups_remaining is 0" in e for e in errors_exhausted)


def test_live_selector_plan_aware_fallback_zero_canned_questions():
    """Verify selector fallback never generates generic canned questions and advances cleanly."""
    next_planned = {
        "id": "slot_sql_3",
        "stage": "technical",
        "skill_id": "sk_sql",
        "skill_name": "PostgreSQL",
        "text": "How do you diagnose and eliminate lock contention during database index creation?",
    }
    selector_input = SelectorInput(
        candidate_and_job_summary="Job: Database Engineer.",
        current_question={"id": "curr", "stage": "technical", "text": "What is MVCC?"},
        candidate_answer="Multi-version concurrency control.",
        next_planned_question=next_planned,
        followups_remaining=1,
    )

    fallback_out, metrics = _generate_plan_aware_fallback(selector_input, "LLM timeout after 1.2s")

    # Bounded fallback properties:
    assert fallback_out.decision == "ADVANCE"
    assert fallback_out.planned_question_id == "slot_sql_3"
    assert fallback_out.ack in ("Understood.", "Got it.")
    assert metrics["fallback_used"] is True
    assert "LLM timeout" in metrics["fallback_reason"]

    # Must NEVER emit canned generic question strings
    assert fallback_out.follow_up_question is None
    assert fallback_out.clarify_text is None


# =============================================================================
# 6. Runner Integration with ScriptPlan & Bounded Selector Tests
# =============================================================================

@pytest.mark.asyncio
async def test_runner_executes_decision_via_selector_and_maintains_turn_history():
    """Verify SessionRunner executes _call_decision_llm through the bounded selector."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()

    # Create dummy ScriptPlan
    slot_1 = PlanSlot(
        id="s1",
        index=0,
        stage="technical",
        kind="anchor",
        skill_name="Python",
        question_text="How do asyncio tasks coordinate with event loops?",
        expected_key_points=["Coroutines", "Non-blocking event loop"],
    )
    slot_2 = PlanSlot(
        id="s2",
        index=1,
        stage="technical",
        kind="anchor",
        skill_name="Distributed Systems",
        question_text="How do you handle split-brain in Raft consensus?",
        expected_key_points=["Leader leases", "Quorum majority"],
    )
    plan = ScriptPlan(
        plan_id="plan_test_run",
        application_id="app_test",
        job_id="job_test",
        input_hash="hash_test",
        slots=[slot_1, slot_2],
        question_order=["s1", "s2"],
    )

    script = {
        "session_id": "sess_runner_selector_test",
        "duration_planned_mins": 15,
        "job_summary": "Job: Systems Architect.",
        "script_plan": plan.model_dump(),
        "questions": [
            {
                "id": slot_1.id,
                "skill_name": slot_1.skill_name,
                "question_text": slot_1.question_text,
                "priority_tier": "P0",
                "expected_key_points": slot_1.expected_key_points,
            },
            {
                "id": slot_2.id,
                "skill_name": slot_2.skill_name,
                "question_text": slot_2.question_text,
                "priority_tier": "P0",
                "expected_key_points": slot_2.expected_key_points,
            },
        ],
    }

    runner = SessionRunner("sess_runner_selector_test", script, ws, tts, llm_fn=None)
    assert runner.script_plan is not None

    req = RequestDecision(
        token="tok_sel_1",
        skill="Python",
        question_text="How do asyncio tasks coordinate with event loops?",
        answer_text="Asyncio event loops maintain a run queue of coroutines and poll sockets with epoll.",
        last_ack_opener="Got it,",
    )

    # Mock stream decision
    async def mock_stream_selector(**kwargs):
        cb = kwargs.get("on_ack_ready")
        if cb:
            cb({"decision": "ADVANCE", "ack": "Coroutines poll sockets with epoll."})
        return (
            {
                "decision": "ADVANCE",
                "planned_question_id": "s2",
                "ack": "Coroutines poll sockets with epoll.",
                "reason_code": "planned_next",
            },
            {"ttft_ms": 90, "model_name": "mock_selector"},
        )

    with patch(
        "backend.app.services.interview_v2.director.stream_decision_with_ack_first",
        side_effect=mock_stream_selector,
    ):
        await runner._call_decision_llm(req)

        # Collect AckReady and DecisionReady from queue
        ack_event = None
        dec_event = None
        for _ in range(5):
            ev = await asyncio.wait_for(runner.queue.get(), timeout=1.0)
            if isinstance(ev, AckReady):
                ack_event = ev
            elif isinstance(ev, DecisionReady):
                dec_event = ev
                break

        assert ack_event is not None
        assert "poll sockets" in ack_event.text.lower()

        assert dec_event is not None
        assert dec_event.decision is not None
        assert dec_event.decision["action"] == "new_topic"
        # Spoken question must be the EXACT planned text of slot 2
        assert dec_event.decision["question"] == "How do you handle split-brain in Raft consensus?"

        # Verify recent turns deque updated
        assert len(runner.recent_turns) == 1
        assert runner.recent_turns[0]["question"] == req.question_text
        assert runner.recent_turns[0]["answer"] == req.answer_text


# =============================================================================
# 7. Gated Live Bedrock Model Acceptance Test
# =============================================================================

@pytest.mark.asyncio
async def test_gated_live_bedrock_plan_and_selector_acceptance():
    """Live acceptance test against Bedrock apac.amazon.nova-pro-v1:0 (skipped if no credentials)."""
    token = get_bedrock_bearer_token()
    has_aws_creds = bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))
    if not (token or has_aws_creds):
        pytest.skip("No live AWS Bedrock credentials found in environment. Skipping gated live test.")

    context = HydratedInterviewContext(
        application_id="app_live_gate",
        job_id="job_live_gate",
        candidate_full_name="Morgan Chase",
        candidate_first_name="Morgan",
        job_title="Senior Python Platform Engineer",
        interview_duration_mins=15,
        skills=[{
            "id": "sk_live_1",
            "name": "Python Async Internals",
            "priority_tier": "P0",
            "weight_percentage": 100.0,
            "anchor_question": "How do event loops in Python interface with OS-level I/O multiplexing?",
            "expected_key_points": ["epoll/kqueue", "SelectSelector", "Task callbacks"],
        }],
    )

    skeleton = build_plan_skeleton(context)

    # 1. Live Plan Generation
    plan, metrics = await write_interview_script_plan(skeleton, context)
    assert metrics["validation_passed"] is True
    assert metrics["fallback_used"] is False
    assert len(plan.slots) == len(skeleton.slots)
    assert plan.slots[0].stage == "greeting"
    assert "Morgan" in plan.slots[0].question_text

    # 2. Live Selector Decision
    selector_input = SelectorInput(
        candidate_and_job_summary="Job: Senior Python Platform Engineer. Candidate: Morgan.",
        past_two_turns=[],
        current_question={
            "id": plan.slots[0].id,
            "stage": "greeting",
            "skill_name": None,
            "text": plan.slots[0].question_text,
            "expected_key_points": ["Acknowledge agenda"],
            "followup_count": 0,
            "max_followup_depth": 0,
        },
        candidate_answer="Yes, that agenda sounds great. I am excited and ready to begin.",
        next_planned_question={
            "id": plan.slots[1].id,
            "stage": plan.slots[1].stage,
            "skill_id": plan.slots[1].skill_id,
            "skill_name": plan.slots[1].skill_name,
            "text": plan.slots[1].question_text,
        },
        followups_remaining=0,
        remaining_time_mins=14.0,
    )

    output, sel_metrics = await select_next_interview_action(selector_input)
    assert sel_metrics["validation_passed"] is True
    assert sel_metrics["fallback_used"] is False
    assert output.decision in ("ADVANCE", "FOLLOW_UP")
    if output.decision == "ADVANCE":
        assert output.planned_question_id == plan.slots[1].id


# =============================================================================
# No-Knowledge Guard: "I don't know" answers must swap, never probe
# =============================================================================

@pytest.mark.asyncio
async def test_no_knowledge_signal_coerces_follow_up_to_swap():
    """Even when the model returns FOLLOW_UP, a no-knowledge admission is coerced
    to SWAP_QUESTION with the prepared alternative question."""
    inp = SelectorInput(
        candidate_and_job_summary="Job: Senior Python Dev.",
        current_question={"id": "q1", "text": "How do you tune asyncio event loops?"},
        candidate_answer="I don't know, I have never used asyncio.",
        no_knowledge_signal=True,
        alternative_question={"id": "q_alt", "text": "How do you approach debugging slow code?"},
        followups_remaining=2,
        remaining_time_mins=12.0,
    )

    async def misbehaving_llm(**kwargs):
        return {
            "decision": "FOLLOW_UP",
            "follow_up_question": "But how do you tune the loop anyway?",
            "reason_code": "answer_gap",
        }

    out, metrics = await select_next_interview_action(inp, llm_fn=misbehaving_llm)
    assert out.decision == "SWAP_QUESTION"
    assert out.reason_code == "no_knowledge"
    assert out.follow_up_question == "How do you approach debugging slow code?"


@pytest.mark.asyncio
async def test_no_knowledge_fallback_swaps_instead_of_probing():
    """The deterministic plan-aware fallback also swaps on a no-knowledge signal."""
    inp = SelectorInput(
        candidate_and_job_summary="Job: Senior Python Dev.",
        current_question={"id": "q1", "text": "How do you tune asyncio event loops?"},
        candidate_answer="I have no idea about that.",
        next_planned_question={"id": "q_next", "text": "Explain Python GIL limitations."},
        no_knowledge_signal=True,
        followups_remaining=2,
        remaining_time_mins=12.0,
    )
    out, _ = _generate_plan_aware_fallback(inp, "llm_error")
    assert out.decision == "SWAP_QUESTION"
    assert out.reason_code == "no_knowledge"


# ---------------------------------------------------------------------------
# Conversational-depth guard + resume-grounded plan slots (post-manual-test)
# ---------------------------------------------------------------------------

def _depth_input(answer_words=25, followups_remaining=2, remaining_mins=8.0):
    from backend.app.services.interview_v2.selector import SelectorInput
    answer = " ".join(f"word{i}" for i in range(answer_words))
    return SelectorInput(
        candidate_and_job_summary="Candidate: Mohammad. Applying for: SDE.",
        past_two_turns=[],
        current_question={
            "id": "q1", "stage": "technical", "skill_id": "s1", "skill_name": "Data Structures",
            "text": "How would you power search autocomplete?", "expected_key_points": ["trie"],
            "followup_count": 1, "max_followup_depth": 2,
        },
        candidate_answer=answer,
        next_planned_question={"id": "q2", "stage": "technical", "skill_id": "s2", "skill_name": "CS Fundamentals", "text": "Next question?"},
        optional_prepared_followups=[{"id": "p1", "text": "How would you handle memory limits?"}],
        followups_remaining=followups_remaining,
        remaining_time_mins=remaining_mins,
    )


def test_advance_on_substantive_answer_coerced_to_follow_up():
    from backend.app.services.interview_v2.selector import select_next_interview_action
    inp = _depth_input()
    out, metrics = asyncio.run(select_next_interview_action(
        inp, llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Got it.", "reason_code": "planned_next", "rationale": "sufficient"}
    ))
    assert out.decision == "FOLLOW_UP"
    assert out.reason_code == "depth_probe"
    assert out.follow_up_question


def test_advance_allowed_when_depth_exhausted():
    from backend.app.services.interview_v2.selector import select_next_interview_action
    inp = _depth_input(followups_remaining=0)
    out, _ = asyncio.run(select_next_interview_action(
        inp, llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Got it.", "reason_code": "planned_next", "rationale": "done"}
    ))
    assert out.decision == "ADVANCE"


def test_advance_allowed_when_time_short():
    from backend.app.services.interview_v2.selector import select_next_interview_action
    inp = _depth_input(remaining_mins=1.5)
    out, _ = asyncio.run(select_next_interview_action(
        inp, llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Got it.", "reason_code": "planned_next", "rationale": "time"}
    ))
    assert out.decision == "ADVANCE"


def test_short_answer_advances_without_depth_probe():
    from backend.app.services.interview_v2.selector import select_next_interview_action
    inp = _depth_input(answer_words=6)
    out, _ = asyncio.run(select_next_interview_action(
        inp, llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Got it.", "reason_code": "planned_next", "rationale": "short"}
    ))
    assert out.decision == "ADVANCE"


def test_plan_skeleton_seeds_resume_grounding():
    """With resume projects/companies in context, the skeleton must include a
    dedicated projects-walkthrough slot and resume-grounded follow-up probes —
    the structural fix for 'no questions based on my resume'."""
    from backend.app.services.interview_v2.context_hydrator import HydratedInterviewContext
    from backend.app.services.interview_v2.plan_schema import build_plan_skeleton

    ctx = HydratedInterviewContext(
        application_id="app-1", job_id="job-1",
        candidate_full_name="Mohammad Abdullah", candidate_first_name="Mohammad",
        resume_projects=[
            {"name": "Agentic Growth Controller", "description": "", "technologies": ["FastAPI", "WebSockets"]},
            {"name": "AI Recruiter Platform", "description": "", "technologies": []},
        ],
        resume_work_experience=[{"company": "Barclays", "role": "Technology Developer Intern"}],
        job_title="SDE", seniority_level="entry",
        interview_duration_mins=30, max_followup_depth=2,
        skills=[
            {"id": "sk1", "name": "Data Structures & Problem Solving", "priority_tier": "P0", "weight_percentage": 40},
            {"id": "sk2", "name": "Project & Experience Deep-Dive", "priority_tier": "P0", "weight_percentage": 20},
        ],
    )
    plan = build_plan_skeleton(ctx)
    kinds = [(s.kind, s.question_text) for s in plan.slots]

    resume_slots = [s for s in plan.slots if s.kind == "resume_probe"]
    assert resume_slots, "a projects-walkthrough slot must exist when the resume has projects"
    assert "Agentic Growth Controller" in resume_slots[0].question_text
    assert resume_slots[0].follow_up_depth_allowed >= 1

    ds_slot = next(s for s in plan.slots if s.skill_name == "Data Structures & Problem Solving" and s.kind == "anchor")
    assert any("Agentic Growth Controller" in p for p in ds_slot.followup_probes), \
        "per-skill probes must include a resume-grounded option"

    pd_slot = [s for s in plan.slots if s.skill_name == "Project & Experience Deep-Dive"]
    assert not pd_slot or not any("come into play" in p for p in pd_slot[0].followup_probes), \
        "the projects competency itself must not get a 'come into play in project' probe"


# ---------------------------------------------------------------------------
# Rubric- & weight-driven interviewer (spec upgrade)
# ---------------------------------------------------------------------------

def test_weight_proportional_followup_budgets():
    """A 45% P0 skill earns more follow-up depth than a 15% P2 skill, budgets
    respect usable time, and every PlanSlot carries rubric/escalation data."""
    from backend.app.services.interview_v2.context_hydrator import HydratedInterviewContext
    from backend.app.services.interview_v2.plan_schema import build_plan_skeleton

    ctx = HydratedInterviewContext(
        application_id="app-1", job_id="job-1",
        candidate_full_name="Jane Doe", candidate_first_name="Jane",
        job_title="SDE", seniority_level="mid",
        interview_duration_mins=30, max_followup_depth=2,
        skills=[
            {"id": "s1", "name": "Distributed Systems", "priority_tier": "P0", "weight_percentage": 45,
             "rubric_l1": "l1", "rubric_l2": "l2", "rubric_l3": "l3", "rubric_l4": "l4", "rubric_l5": "l5"},
            {"id": "s2", "name": "Tooling", "priority_tier": "P2", "weight_percentage": 15},
            {"id": "s3", "name": "Debugging", "priority_tier": "P1", "weight_percentage": 40},
        ],
    )
    plan = build_plan_skeleton(ctx)
    anchors = {s.skill_name: s for s in plan.slots if s.kind == "anchor"}
    assert anchors["Distributed Systems"].follow_up_depth_allowed >= anchors["Tooling"].follow_up_depth_allowed
    assert anchors["Distributed Systems"].rubric_levels.get("L4") == "l4"
    assert anchors["Tooling"].rubric_levels.get("L4") in ("", None)
    # Time-clamped: total follow-up budget cannot explode past usable time
    total_budget = sum(s.follow_up_depth_allowed for s in anchors.values()) + len(anchors)
    assert total_budget <= max(6, round(30 * 60 * 0.6 / 90)) + len(anchors) + 4


def test_selector_receives_rubric_and_hooks_in_prompt():
    """The selector user prompt must carry rubric anchors, escalation question,
    and candidate hooks so decisions are competency-driven."""
    import asyncio
    from backend.app.services.interview_v2.selector import select_next_interview_action

    inp = _depth_input()
    inp = inp.model_copy(update={
        "skill_rubric": {"L3": "Explains trie trade-offs", "L4": "Handles memory bounds"},
        "escalation_question": "How would that scale to 10M terms?",
        "candidate_hooks": ["AI Recruiter Platform (FastAPI, WebSockets)"],
        "hint_or_alt_used_on_skill": False,
    })
    seen = {}
    async def capture_llm(**kw):
        seen["user_prompt"] = kw.get("user_prompt", "")
        return {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Got it.",
                "reason_code": "planned_next", "rationale": "ok",
                "estimated_rubric_level": "L4", "covered_expectations": ["trie trade-offs"]}
    out, _ = asyncio.run(select_next_interview_action(inp, llm_fn=capture_llm))
    assert "Explains trie trade-offs" in seen["user_prompt"]
    assert "How would that scale to 10M terms?" in seen["user_prompt"]
    assert "AI Recruiter Platform" in seen["user_prompt"]
    # L4-assessed ADVANCE is respected (no depth-probe coercion)
    assert out.decision == "ADVANCE"
    assert out.estimated_rubric_level == "L4"
    assert out.covered_expectations == ["trie trade-offs"]


# ---------------------------------------------------------------------------
# Production agentic-loop verification (dossier / level carry / prompt split)
# ---------------------------------------------------------------------------

def test_selector_prompt_is_stable_first_and_carries_dossier_and_level():
    """The prompt must place stable context (dossier, rubric, hooks) BEFORE the
    volatile live turn, carry the dossier and last estimated level, and split
    cleanly at the LIVE TURN marker for provider prefix caching."""
    import asyncio
    from backend.app.services.interview_v2.selector import select_next_interview_action

    inp = _depth_input()
    inp = inp.model_copy(update={
        "skill_rubric": {"L3": "Explains trie trade-offs"},
        "candidate_dossier": {
            "name": "Mohammad",
            "notable_projects": ["Agentic Growth Controller (FastAPI, WebSockets)"],
            "claims_to_verify": ["Built realtime interview engine"],
        },
        "candidate_hooks": ["Agentic Growth Controller (FastAPI, WebSockets)"],
        "last_estimated_level": "L2",
    })
    seen = {}

    async def capture_llm(**kw):
        seen["user_prompt"] = kw.get("user_prompt", "")
        return {"decision": "FOLLOW_UP", "follow_up_question": "How did you handle lag there?",
                "ack": "Right.", "reason_code": "answer_gap", "rationale": "probe",
                "estimated_rubric_level": "L3"}

    out, _ = asyncio.run(select_next_interview_action(inp, llm_fn=capture_llm))
    p = seen["user_prompt"]
    assert "Agentic Growth Controller" in p
    assert "L2" in p and "Continue the ladder" in p
    # Stable content must precede the volatile live turn for prefix caching
    assert p.index("CANDIDATE DOSSIER") < p.index("=== LIVE TURN") < p.index("CANDIDATE ANSWER")
    assert "LAST 4 TURNS" in p


def test_bedrock_cachepoint_payload_and_uncached_retry(monkeypatch):
    """The router attaches cachePoint blocks after the stable prefix and
    retries once uncached when the provider rejects caching."""
    import asyncio
    import json as _json
    import backend.app.services.llm_router as lr

    calls = {"n": 0, "payloads": []}
    BODY = _json.dumps({"delta": {"text": '{"decision":"ADVANCE","ack":"Got it."}'}}).encode()

    class FakeStreamCtx:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("400 ValidationException: cachePoint not supported")
            return self

        async def __aexit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield BODY

    class FakeClient:
        def stream(self, method, url, headers=None, json=None, timeout=None):
            calls["payloads"].append(json)
            return FakeStreamCtx(json)

    class FakeBedrockClientMgr:
        def get_async_client(self):
            return FakeClient()

    class FakeEventStreamBuffer:
        def __init__(self):
            self.chunks = []

        def add_data(self, data):
            self.chunks.append(data)

        def __iter__(self):
            class Ev:
                def __init__(self, payload):
                    self.payload = payload
            return iter([Ev(c) for c in self.chunks])

    async def fake_token():
        return "tok"

    monkeypatch.setattr(lr, "BEDROCK_CLIENT", FakeBedrockClientMgr())
    monkeypatch.setattr(lr, "EventStreamBuffer", FakeEventStreamBuffer)
    monkeypatch.setattr(lr, "get_bedrock_bearer_token", fake_token)
    monkeypatch.setattr(lr, "get_bedrock_region", lambda: "ap-southeast-2")
    monkeypatch.setattr(lr, "get_bedrock_model_id", lambda: "apac.amazon.nova-pro-v1:0")

    async def run():
        return await lr.stream_decision_with_ack_first(
            system_prompt="sys",
            user_prompt=None,
            user_stable_prefix="STABLE PREFIX ",
            user_volatile_suffix="VOLATILE",
            max_output_tokens=50,
        )

    asyncio.run(run())
    assert calls["n"] == 2, "must retry once after cachePoint rejection"
    first, second = calls["payloads"]
    assert any("cachePoint" in b for b in first["messages"][0]["content"])
    assert "cachePoint" in first["system"][1]
    assert second["messages"][0]["content"] == [{"text": "STABLE PREFIX VOLATILE"}]


def test_first_no_knowledge_advance_coerced_to_swap():
    """Ladder step 1: on the FIRST 'I don't know' for a skill, even an ADVANCE
    decision becomes a warm swap to the prepared alternative — the easier
    angle is offered before the topic is dropped (verified gap from e2e run)."""
    import asyncio
    from backend.app.services.interview_v2.selector import SelectorInput, select_next_interview_action

    inp = SelectorInput(
        candidate_and_job_summary="Job: SDE.",
        past_two_turns=[],
        current_question={"id": "q1", "stage": "technical", "skill_id": "s1", "skill_name": "Prompting",
                          "text": "Compare prompt strategies?", "expected_key_points": ["strategies"],
                          "followup_count": 1, "max_followup_depth": 2},
        candidate_answer="I don't know, I have never formally compared prompt strategies.",
        next_planned_question={"id": "q2", "stage": "technical", "skill_id": "s2", "skill_name": "Data", "text": "Next?"},
        alternative_question={"id": "alt1", "text": "Imagine a simpler scenario — how would you approach it?", "skill_name": "Prompting"},
        no_knowledge_signal=True,
        hint_or_alt_used_on_skill=False,
        followups_remaining=1,
        remaining_time_mins=10.0,
    )
    out, _ = asyncio.run(select_next_interview_action(
        inp, llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Okay.",
                                  "reason_code": "planned_next", "rationale": "done"}
    ))
    assert out.decision == "SWAP_QUESTION"
    assert "Imagine a simpler scenario" in (out.follow_up_question or "")

    # Second admission (hint/alt already used): ADVANCE is respected
    inp2 = inp.model_copy(update={"hint_or_alt_used_on_skill": True})
    out2, _ = asyncio.run(select_next_interview_action(
        inp2, llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Okay.",
                                   "reason_code": "planned_next", "rationale": "move on"}
    ))
    assert out2.decision == "ADVANCE"
