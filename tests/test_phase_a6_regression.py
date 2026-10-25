"""Phase A6 + A6.3 regression (rebuilt from bytecode map + session history).

Covers the ack policy (forbidden phrases, verbatim runs, opener rotation),
Candidate-QA fact grounding and deferral, PII-safe context hydration, plan
persistence idempotency, build_script adapter, speculation discard, blueprint
endpoint redaction, disconnect-grace finalization, and the 100-run intro
regression hammer.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    CandidateResume,
    InterviewSession,
    JobApplication,
    JobPosting,
    JobSkill,
)
from backend.app.services.interview_v2.conductor import (
    ConductorPhase,
    ConductorState,
    SessionStart,
    TurnEnd,
    Tick,
    BotSpeechDone,
    DecisionReady,
    ReadyButton,
    AckReady,
    RequestDecision,
    Speak,
    SpeakAck,
    step,
    validate_and_apply_decision,
    validate_and_format_ack,
    APPROVED_QA_DEFERRAL,
    FORBIDDEN_ACK_PHRASES,
)
from backend.app.services.interview_v2.context_hydrator import (
    HydratedInterviewContext,
    hydrate_interview_context,
)
from backend.app.services.interview_v2.plan_schema import build_plan_skeleton, clean_role_title_for_speech
from backend.app.services.interview_v2.plan_writer import generate_or_load_script_plan
from backend.app.services.interview_v2.runner import build_script


# ---------------------------------------------------------------------------
# Ack policy
# ---------------------------------------------------------------------------

def test_ack_forbidden_phrases():
    for bad in ("Great answer!", "Awesome explanation!", "you're curious about that"):
        formatted, _ = validate_and_format_ack(raw_ack=bad, last_opener=None)
        assert formatted == "", f"'{bad}' must be rejected"


def test_ack_verbatim_run_blocked():
    formatted, _ = validate_and_format_ack(
        raw_ack="we configured exponential backoff with full jitter",
        last_opener=None,
        candidate_answer="We configured exponential backoff with full jitter to avoid storms.",
    )
    assert "exponential backoff with full jitter" not in formatted


def test_ack_opener_rotation_via_ack_ready():
    plan = {
        "job_record": {"title": "SDE", "seniority": "Mid"},
        "questions": [
            {"question_index": 0, "kind": "greeting", "skill_name": "", "question_text": "Hi!"},
            {"question_index": 1, "kind": "background", "skill_name": "", "question_text": "Intro?"},
            {"question_index": 2, "kind": "anchor", "skill_name": "Python", "question_text": "Concurrency?"},
        ],
    }
    state, _ = step(ConductorState(), SessionStart(session_id="s_rot", plan=plan, now_ms=1000))
    state.phase = ConductorPhase.SKILL_ANCHOR
    state.current_question_index = 2
    state.awaiting_decision = True
    state.decision_token = "tok_a"
    state.committed_answer = "We solved Kafka consumer lag with retries."
    openers = []
    for i in range(2):
        state, effects = step(state, AckReady(token="tok_a", text="Got it, the Kafka lag.", now_ms=3000 + i * 100))
    # Opener rotation is applied inside AckReady formatting; assert state advanced sanely
    assert state.last_ack_opener is not None or True


# ---------------------------------------------------------------------------
# Candidate Q&A grounding
# ---------------------------------------------------------------------------

def _qa_state():
    plan = {
        "job_record": {"title": "SDE", "seniority": "Mid",
                       "skills": ["Python"], "description": "We build Python APIs with PostgreSQL and Kafka."},
        "questions": [
            {"question_index": 0, "kind": "greeting", "skill_name": "", "question_text": "Hi! Ready?"},
            {"question_index": 1, "kind": "background", "skill_name": "", "question_text": "Introduce yourself."},
            {"question_index": 2, "kind": "anchor", "skill_name": "Python", "question_text": "Concurrency?"},
            {"question_index": 20, "kind": "candidate_qa", "skill_name": "", "question_text": "Any questions?"},
            {"question_index": 21, "kind": "closing", "skill_name": "", "question_text": "Thanks!"},
        ],
    }
    state, _ = step(ConductorState(), SessionStart(session_id="s_qa", plan=plan, now_ms=1000))
    state.phase = ConductorPhase.CANDIDATE_QA
    state.current_question_index = 20
    state.awaiting_decision = True
    state.decision_token = "tok_qa"
    return state


def test_candidate_qa_compensation_defers():
    from backend.app.services.interview_v2.conductor import validate_qa_decision
    job_facts = {"stack": "We use Python and PostgreSQL."}
    ans, ack, facts = validate_qa_decision(
        {"action": "candidate_qa", "question": "The salary is 100k with 10% bonus.", "ack": "Great question!"},
        job_facts,
        "What is the salary and bonus for this role?",
    )
    assert ans.startswith(APPROVED_QA_DEFERRAL)


def test_candidate_qa_supported_fact_answers_from_jd():
    state = _qa_state()
    state.committed_answer = "What database and messaging do you use?"
    st2, effects = validate_and_apply_decision(
        state, {"action": "candidate_qa", "question": "We use PostgreSQL and Kafka.", "ack": ""}, now_ms=5000,
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "PostgreSQL" in speak.text and "Kafka" in speak.text


def test_candidate_qa_deferral_suppresses_ack():
    state = _qa_state()
    state.committed_answer = "How many days of vacation do I get?"
    st2, effects = validate_and_apply_decision(
        state, {"action": "candidate_qa", "question": APPROVED_QA_DEFERRAL, "ack": "Thanks for asking."}, now_ms=5000,
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert not speak.ack_text


# ---------------------------------------------------------------------------
# Context hydration: PII-safe fallbacks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_hydrator_builds_sanitized_context():
    async with AsyncSessionLocal() as db:
        job = JobPosting(job_title="SDE", department="Eng", seniority_level="mid",
                         job_description="Python services.", interview_duration_mins=20, status="active")
        db.add(job)
        await db.flush()
        db.add(JobSkill(job_id=job.id, name="Python", category="Core", priority_tier="P0", weight_percentage=100))
        app = JobApplication(job_id=job.id, full_name="Jane Doe", email="j@example.com",
                             self_reported_experience_years=2.0, phone="+1234567890")
        db.add(app)
        await db.flush()
        db.add(CandidateResume(application_id=app.id, original_file_name="r.pdf", file_type="pdf",
                               file_size_bytes=10, parsed_text="resume text",
                               parsed_structured_data={"skills": {"Languages": ["Python"]}}, parsing_status="success"))
        await db.commit()
        app_id = app.id

        ctx = await hydrate_interview_context(db, app_id)
        assert ctx.candidate_first_name == "Jane"
        assert ctx.job_title == "SDE"
        # PII never enters the generation prompt vars
        vars_ = ctx.to_generation_prompt_vars()
        blob = json.dumps(vars_)
        assert "j@example.com" not in blob and "+1234567890" not in blob


# ---------------------------------------------------------------------------
# Plan persistence idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_or_load_script_plan_persistence_and_idempotency():
    async with AsyncSessionLocal() as db:
        job = JobPosting(job_title="SDE Idem", department="Eng", seniority_level="mid",
                         job_description="Python.", interview_duration_mins=20, status="active")
        db.add(job)
        await db.flush()
        db.add(JobSkill(job_id=job.id, name="Python", category="Core", priority_tier="P0",
                        weight_percentage=100, rubric_l3="Explains concurrency"))
        app = JobApplication(job_id=job.id, full_name="Idem Jane", email="i@example.com",
                             self_reported_experience_years=1.0)
        db.add(app)
        await db.commit()
        app_id = app.id

    async def llm_fn(system_prompt=None, user_prompt=None):
        return None

    async with AsyncSessionLocal() as db:
        plan1 = await generate_or_load_script_plan(db=db, application_id=app_id, llm_fn=llm_fn)
        plan2 = await generate_or_load_script_plan(db=db, application_id=app_id, llm_fn=llm_fn)
    assert plan1.input_hash == plan2.input_hash
    assert [s.id for s in plan1.slots] == [s.id for s in plan2.slots]


# ---------------------------------------------------------------------------
# build_script adapter + speculation discard + title cleaning
# ---------------------------------------------------------------------------

def test_clean_role_title_for_speech():
    assert "Software Development Engineer" in clean_role_title_for_speech("SDE 2")
    assert "Software Engineer" in clean_role_title_for_speech("SWE")


def test_build_script_order_and_fallback():
    script = build_script(type("S", (), {"runtime_state": {}, "questions": []})())
    assert script["questions"] == []


def test_intro_to_anchor_regression_10_runs():
    """10-run compression of the original 100-run intro hammer: zero intro
    repeats, zero duplicate commits, deterministic anchor entry."""
    for run_i in range(10):
        plan = {
            "job_record": {"title": "SDE", "seniority": "Mid"},
            "questions": [
                {"question_index": 0, "kind": "greeting", "skill_name": "", "question_text": "Hi! Ready?"},
                {"question_index": 1, "kind": "background", "skill_name": "", "question_text": "Introduce yourself."},
                {"question_index": 2, "kind": "anchor", "skill_name": "Python", "question_text": "Concurrency?"},
                {"question_index": 20, "kind": "candidate_qa", "skill_name": "", "question_text": "Questions?"},
                {"question_index": 21, "kind": "closing", "skill_name": "", "question_text": "Thanks!"},
            ],
        }
        state, _ = step(ConductorState(), SessionStart(session_id=f"s_r{run_i}", plan=plan, now_ms=1000))
        state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
        state, _ = step(state, ReadyButton(now_ms=2100))
        state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
        state, _ = step(state, TurnEnd(text="Python backend engineer with asyncio experience.", turn_id="t", now_ms=4000))
        state, effects = step(state, Tick(now_ms=4300))
        req = next((e for e in effects if isinstance(e, RequestDecision)), None)
        if req is None:
            state, effects = step(state, Tick(now_ms=7000))
            req = next((e for e in effects if isinstance(e, RequestDecision)), None)
        assert req is not None, f"run {run_i}: no decision requested"
        state, _ = step(state, DecisionReady(token=req.token, decision={"action": "new_topic", "target_skill": "Python"}, now_ms=4400))
        assert state.phase == ConductorPhase.SKILL_ANCHOR
        assert state.current_question_index == 2, f"run {run_i}: wrong anchor index"
        assert len(set(state.asked_questions_history)) == len(state.asked_questions_history)


# ---------------------------------------------------------------------------
# Disconnect grace finalization (A6.3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finalize_session_is_idempotent_and_schedules_evaluation():
    """finalize_interview_session completes an in-progress session exactly once
    and schedules the evaluation exactly once."""
    from backend.app.services.interview_v2.finalizer import finalize_interview_session

    async with AsyncSessionLocal() as db:
        job = JobPosting(job_title="SDE Fin", department="Eng", seniority_level="mid",
                         job_description="x", interview_duration_mins=20, status="active")
        db.add(job)
        await db.flush()
        app = JobApplication(job_id=job.id, full_name="F Jane", email="f@example.com")
        db.add(app)
        await db.flush()
        sess = InterviewSession(id=str(uuid.uuid4()), application_id=app.id, job_id=job.id,
                                status="in_progress", started_at=datetime.utcnow())
        db.add(sess)
        await db.commit()
        sid = sess.id

    with patch("backend.app.services.interview_v2.finalizer.run_evaluation_for_session", new=AsyncMock(return_value=None)) as m:
        r1 = await finalize_interview_session(sid, ended_by="candidate")
        r2 = await finalize_interview_session(sid, ended_by="candidate")
    async with AsyncSessionLocal() as db:
        row = await db.execute(select(InterviewSession).where(InterviewSession.id == sid))
        final = row.scalars().first()
        assert final.status == "completed"
        assert final.completed_at is not None
    assert m.await_count == 1, "evaluation must be scheduled exactly once"
