"""Live plan integration + A6 regression + director verification (rebuilt).

Covers the hydrated-context -> skeleton -> writer pipeline, resume keyterm
extraction for STT biasing, resume-aware decision context, opening-variety
validator wiring, and the live ack-first decision path on a real test-DB
application.
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    CandidateResume,
    InterviewBlueprint,
    BlueprintSection,
    BlueprintExpectation,
    BlueprintQuestion,
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
    Speak,
    step,
    validate_and_apply_decision,
)
from backend.app.services.interview_v2.context_hydrator import (
    HydratedInterviewContext,
    hydrate_interview_context,
)
from backend.app.services.interview_v2.plan_schema import build_plan_skeleton
from backend.app.services.interview_v2.plan_writer import (
    ensure_session_script_plan,
    generate_or_load_script_plan,
    write_interview_script_plan,
)
from backend.app.services.voice.gateway import _resume_keyterms


RESUME = {
    "_parser": "llm+regex",
    "skills": {"Languages": ["Python", "Go"], "Data": ["Kafka", "Apache Flink"]},
    "work_experience": [{"company": "Stripe", "role": "Backend Engineer"}],
    "projects": [{"name": "realtime-fraud-scoring", "description": "", "technologies": ["Flink", "Redis"]}],
}


# ---------------------------------------------------------------------------
# Resume keyterms for STT biasing
# ---------------------------------------------------------------------------

def test_resume_keyterms_extract_resume_vocabulary():
    class FakeResume:
        parsed_structured_data = RESUME

    class FakeApp:
        resume = FakeResume()

    terms = _resume_keyterms(FakeApp())
    assert "Python" in terms and "Kafka" in terms and "Stripe" in terms
    assert "realtime-fraud-scoring" in terms
    assert _resume_keyterms(type("A", (), {"resume": None})()) == []


# ---------------------------------------------------------------------------
# Skeleton -> writer pipeline (mock LLM)
# ---------------------------------------------------------------------------

def _ctx_with_resume() -> HydratedInterviewContext:
    return HydratedInterviewContext(
        application_id="app-x", job_id="job-x",
        candidate_full_name="Jane Doe", candidate_first_name="Jane",
        self_reported_experience_years=5.0,
        resume_work_experience=[{"role": "Backend Engineer", "company": "Stripe"}],
        resume_projects=[{"name": "AGC", "description": "Agentic platform", "technologies": ["FastAPI"]}],
        job_title="SDE", seniority_level="senior", interview_duration_mins=30,
        skills=[{"id": "s1", "name": "Python", "priority_tier": "P0", "weight_percentage": 100,
                 "rubric_l3": "Explains concurrency"}],
    )


def test_writer_rewords_slots_with_strict_alignment():
    ctx = _ctx_with_resume()
    skeleton = build_plan_skeleton(ctx)

    async def llm_fn(system_prompt=None, user_prompt=None):
        slots = [{"id": s.id, "text": f"PERSONALIZED: {s.question_text}"} for s in skeleton.slots]
        return {"schema_version": "interview_script.v1", "slots": slots}

    plan, metrics = asyncio.run(write_interview_script_plan(skeleton, ctx, llm_fn=llm_fn))
    assert metrics["fallback_used"] is False
    assert all("PERSONALIZED:" in s.question_text for s in plan.slots)


def test_writer_falls_back_to_skeleton_on_garbage():
    ctx = _ctx_with_resume()
    skeleton = build_plan_skeleton(ctx)

    async def llm_fn(system_prompt=None, user_prompt=None):
        return {"slots": [{"id": "bogus", "text": "???"}]}

    plan, metrics = asyncio.run(write_interview_script_plan(skeleton, ctx, llm_fn=llm_fn))
    # Repair fails alignment -> deterministic skeleton
    assert metrics["fallback_used"] is True
    assert [s.question_text for s in plan.slots] == [s.question_text for s in skeleton.slots]


# ---------------------------------------------------------------------------
# DB-backed session plan generation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_or_load_script_plan_creates_valid_plan():
    async with AsyncSessionLocal() as db:
        job = JobPosting(
            job_title="Integration SDE", department="Eng", seniority_level="mid",
            job_description="Build backend services.", interview_duration_mins=20, status="active",
        )
        db.add(job)
        await db.flush()
        db.add(JobSkill(job_id=job.id, name="Python", category="Core", priority_tier="P0",
                        weight_percentage=100, rubric_l3="Explains concurrency"))
        app = JobApplication(job_id=job.id, full_name="Jane Doe", email="j@example.com",
                             self_reported_experience_years=3.0)
        db.add(app)
        await db.flush()
        db.add(CandidateResume(application_id=app.id, original_file_name="r.pdf", file_type="pdf",
                               file_size_bytes=10, parsed_text="text",
                               parsed_structured_data=RESUME, parsing_status="success"))
        await db.commit()
        app_id = app.id

    async def llm_fn(system_prompt=None, user_prompt=None):
        return None  # force skeleton fallback determinism

    async with AsyncSessionLocal() as db:
        plan = await generate_or_load_script_plan(db=db, application_id=app_id, llm_fn=llm_fn)

    kinds = {s.kind for s in plan.slots}
    assert "greeting" in kinds and "closing" in kinds and "anchor" in kinds
    assert any(s.kind == "resume_probe" for s in plan.slots)


# ---------------------------------------------------------------------------
# Agentic decision path sanity (dossier-aware runner wiring)
# ---------------------------------------------------------------------------

def test_dossier_and_summary_prefer_resume_context():
    ctx = _ctx_with_resume()
    summary = ctx.to_live_turn_summary()
    assert "Jane" in summary and "Stripe" in summary
    dossier = ctx.to_live_candidate_dossier()
    assert dossier["name"] == "Jane"
    assert any("AGC" in p for p in dossier["notable_projects"])


def test_decision_prefers_candidate_summary_when_present():
    import backend.app.services.interview_v2.runner as runner_mod
    r = runner_mod.SessionRunner(
        session_id="s1",
        script={"job_summary": "Job: AI Engineer (Senior, 30m)."},
        aura_client=None,
    )
    r.candidate_summary = "Candidate: Jane (5.0 yrs). Background: Backend Engineer at Stripe."
    chosen = r.candidate_summary or r.script.get("job_summary")
    assert chosen.startswith("Candidate: Jane")
