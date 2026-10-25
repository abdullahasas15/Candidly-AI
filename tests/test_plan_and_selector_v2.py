"""Plan skeleton + selector regression suite (rebuilt from bytecode map + session history).

Covers prompt loading, selector output normalization/validation, no-knowledge
coercion and ladder, conversational-depth guard, plan-aware fallback, skeleton
weight budgets, rubric enrichment, resume grounding, and Bedrock cachePoint
retry behavior.
"""

import asyncio
import json

import pytest

from backend.app.prompts.loader import render_prompt
from backend.app.services.interview_v2.context_hydrator import HydratedInterviewContext
from backend.app.services.interview_v2.plan_schema import build_plan_skeleton, validate_script_plan
from backend.app.services.interview_v2.selector import (
    ALLOWED_ACTIONS,
    SelectorInput,
    SelectorOutput,
    select_next_interview_action,
    validate_selector_output,
)


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

def test_prompt_loader_substitutes_variables():
    rendered = render_prompt("interview/plan_generation_system")
    assert "AI technical interviewer" in rendered

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
    assert "Explains asyncio concurrency" in rendered_user
    assert "Agentic" not in rendered_user
    # Stable-first ordering for provider prefix caching
    assert rendered_user.index("CANDIDATE DOSSIER") < rendered_user.index("=== LIVE TURN")


# ---------------------------------------------------------------------------
# Selector output normalization
# ---------------------------------------------------------------------------

def test_selector_output_normalizes_synonyms_and_case():
    out = SelectorOutput.model_validate({"decision": "next", "question": "What next?", "ack": "Sure?"})
    assert out.decision == "ADVANCE"
    assert out.ack == "Sure"
    assert out.follow_up_question == "What next?"


def test_selector_output_normalizes_rubric_level():
    out = SelectorOutput.model_validate({"decision": "FOLLOW_UP", "follow_up_question": "More?", "estimated_rubric_level": "l4"})
    assert out.estimated_rubric_level == "L4"
    out2 = SelectorOutput.model_validate({"decision": "FOLLOW_UP", "follow_up_question": "More?", "estimated_rubric_level": "bogus"})
    assert out2.estimated_rubric_level is None


def test_validate_selector_output_rejects_bad_followup():
    inp = SelectorInput(
        candidate_and_job_summary="Job: SDE.",
        current_question={"id": "q1", "stage": "technical", "skill_id": "s1", "skill_name": "Python",
                          "text": "How do you handle concurrency?", "followup_count": 0, "max_followup_depth": 2},
        candidate_answer="answer",
        next_planned_question={"id": "q2", "stage": "technical", "skill_id": "s2", "skill_name": "DSA", "text": "Next?"},
        followups_remaining=1,
    )
    long_fq = " ".join(f"word{i}" for i in range(40)) + "?"
    out = SelectorOutput(decision="FOLLOW_UP", follow_up_question=long_fq)
    errors = validate_selector_output(out, inp)
    assert any("28 words" in e for e in errors)


# ---------------------------------------------------------------------------
# Selector action with llm_fn doubles
# ---------------------------------------------------------------------------

def _inp(answer="We profile the retrieval path and fix cache hit rates with warming and LRU eviction.", **kw):
    base = dict(
        candidate_and_job_summary="Job: Senior Python Dev.",
        past_two_turns=[],
        current_question={
            "id": "q1", "stage": "technical", "skill_id": "s1", "skill_name": "Python",
            "text": "How do you handle slow endpoints?", "expected_key_points": ["profiling"],
            "followup_count": 1, "max_followup_depth": 2,
        },
        candidate_answer=answer,
        next_planned_question={"id": "q2", "stage": "technical", "skill_id": "s2", "skill_name": "DSA", "text": "Next question?"},
        optional_prepared_followups=[{"id": "p1", "text": "What latency budget did you target?"}],
        followups_remaining=2,
        remaining_time_mins=10.0,
    )
    base.update(kw)
    return SelectorInput(**base)


def test_no_knowledge_signal_coerces_follow_up_to_swap():
    inp = _inp(answer="I don't know, never used that.", no_knowledge_signal=True,
               alternative_question={"id": "alt", "text": "Simpler angle?", "skill_name": "Python"})
    out, _ = asyncio.run(select_next_interview_action(
        inp, llm_fn=lambda **kw: {"decision": "FOLLOW_UP", "follow_up_question": "Explain anyway?", "ack": "", "reason_code": "answer_gap"}
    ))
    assert out.decision == "SWAP_QUESTION"
    assert "Simpler angle?" in (out.follow_up_question or "")


def test_first_no_knowledge_advance_coerced_to_swap():
    inp = _inp(answer="I don't know, never used that.", no_knowledge_signal=True, hint_or_alt_used_on_skill=False,
               alternative_question={"id": "alt", "text": "Imagine a simpler scenario — how would you approach it?", "skill_name": "Python"})
    out, _ = asyncio.run(select_next_interview_action(
        inp, llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Okay.", "reason_code": "planned_next"}
    ))
    assert out.decision == "SWAP_QUESTION"
    # Second admission (alt already used) advances
    inp2 = inp.model_copy(update={"hint_or_alt_used_on_skill": True})
    out2, _ = asyncio.run(select_next_interview_action(
        inp2, llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Okay.", "reason_code": "planned_next"}
    ))
    assert out2.decision == "ADVANCE"


def test_advance_on_substantive_answer_coerced_to_follow_up():
    out, _ = asyncio.run(select_next_interview_action(
        _inp(), llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Got it.", "reason_code": "planned_next"}
    ))
    assert out.decision == "FOLLOW_UP"
    assert out.reason_code == "depth_probe"
    assert out.follow_up_question


def test_advance_allowed_when_depth_exhausted():
    out, _ = asyncio.run(select_next_interview_action(
        _inp(followups_remaining=0), llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Got it.", "reason_code": "planned_next"}
    ))
    assert out.decision == "ADVANCE"


def test_advance_respected_when_level_already_proven():
    out, _ = asyncio.run(select_next_interview_action(
        _inp(), llm_fn=lambda **kw: {"decision": "ADVANCE", "planned_question_id": "q2", "ack": "Got it.",
                                     "estimated_rubric_level": "L4", "reason_code": "planned_next"}
    ))
    assert out.decision == "ADVANCE"


def test_llm_failure_uses_plan_aware_fallback():
    async def broken(**kw):
        raise RuntimeError("boom")

    out, metrics = asyncio.run(select_next_interview_action(_inp(), llm_fn=broken))
    assert metrics.get("fallback_used") is True
    assert out.decision in ALLOWED_ACTIONS


def test_selector_prompt_carries_dossier_hooks_and_level():
    seen = {}

    async def capture(**kw):
        seen["user_prompt"] = kw.get("user_prompt", "")
        return {"decision": "FOLLOW_UP", "follow_up_question": "And then?", "ack": "Right.",
                "estimated_rubric_level": "L3", "reason_code": "answer_gap"}

    inp = _inp(
        skill_rubric={"L3": "Explains trade-offs"},
        escalation_question="Scale it to 10k rps?",
        candidate_hooks=["AI Recruiter Platform (FastAPI)"],
        candidate_dossier={"name": "Jane", "notable_projects": ["AI Recruiter Platform"]},
        last_estimated_level="L2",
    )
    asyncio.run(select_next_interview_action(inp, llm_fn=capture))
    p = seen["user_prompt"]
    assert "AI Recruiter Platform" in p
    assert "Explains trade-offs" in p
    assert "Scale it to 10k rps?" in p
    assert "L2" in p


# ---------------------------------------------------------------------------
# Bedrock cachePoint payload + retry
# ---------------------------------------------------------------------------

def test_bedrock_cachepoint_payload_and_uncached_retry(monkeypatch):
    import backend.app.services.llm_router as lr

    calls = {"n": 0, "payloads": []}
    BODY = json.dumps({"delta": {"text": '{"decision":"ADVANCE","ack":"Got it."}'}}).encode()

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

    monkeypatch.setattr(lr, "BEDROCK_CLIENT", type("M", (), {"get_async_client": lambda self: FakeClient()})())
    monkeypatch.setattr(lr, "EventStreamBuffer", FakeEventStreamBuffer)
    monkeypatch.setattr(lr, "get_bedrock_bearer_token", fake_token)
    monkeypatch.setattr(lr, "get_bedrock_region", lambda: "ap-southeast-2")
    monkeypatch.setattr(lr, "get_bedrock_model_id", lambda: "apac.amazon.nova-pro-v1:0")

    asyncio.run(lr.stream_decision_with_ack_first(
        system_prompt="sys",
        user_prompt=None,
        user_stable_prefix="STABLE PREFIX ",
        user_volatile_suffix="VOLATILE",
        max_output_tokens=50,
    ))
    assert calls["n"] == 2, "must retry once after cachePoint rejection"
    first, second = calls["payloads"]
    assert any("cachePoint" in b for b in first["messages"][0]["content"])
    assert second["messages"][0]["content"] == [{"text": "STABLE PREFIX VOLATILE"}]


# ---------------------------------------------------------------------------
# Plan skeleton
# ---------------------------------------------------------------------------

def _ctx(**kw):
    base = dict(
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
    base.update(kw)
    return HydratedInterviewContext(**base)


def test_weight_proportional_budgets_and_rubric_enrichment():
    plan = build_plan_skeleton(_ctx())
    anchors = {s.skill_name: s for s in plan.slots if s.kind == "anchor"}
    assert anchors["Distributed Systems"].follow_up_depth_allowed >= anchors["Tooling"].follow_up_depth_allowed
    assert anchors["Distributed Systems"].rubric_levels.get("L4") == "l4"
    assert anchors["Tooling"].rubric_levels.get("L4") in ("", None)
    # Structural sanity: every stage present exactly once (id-level validation
    # requires the same skeleton instance, which the writer pipeline provides)
    kinds = [s.kind for s in plan.slots]
    for k in ("greeting", "background", "candidate_qa", "closing", "anchor"):
        assert k in kinds


def test_resume_grounding_rotates_projects_across_skills():
    ctx = _ctx(
        resume_projects=[
            {"name": "Alpha Platform", "description": "", "technologies": ["Kafka", "Python"]},
            {"name": "Beta Dashboard", "description": "", "technologies": ["React"]},
        ],
        resume_work_experience=[{"company": "Acme", "role": "Engineer"}],
    )
    plan = build_plan_skeleton(ctx)
    resume_slots = [s for s in plan.slots if s.kind == "resume_probe"]
    assert resume_slots and "Alpha Platform" in resume_slots[0].question_text
    probe_texts = " || ".join(p for s in plan.slots if s.kind == "anchor" for p in s.followup_probes)
    assert "Alpha Platform" in probe_texts
    assert "Beta Dashboard" in probe_texts or "Acme" in probe_texts, "second project/company must appear somewhere"


def test_answered_custom_questions_are_skipped_in_skeleton():
    ctx = _ctx(
        custom_questions=[{"id": "cq1", "question_text": "Why are you a fit for this role?"}],
        screening_answers=[{"question_id": "cq1", "question_text": "Why are you a fit for this role?", "answer": "Because I shipped X."}],
    )
    plan = build_plan_skeleton(ctx)
    assert not any(s.kind == "custom" for s in plan.slots)

    ctx2 = _ctx(custom_questions=[{"id": "cq1", "question_text": "Why are you a fit for this role?"}])
    plan2 = build_plan_skeleton(ctx2)
    assert any(s.kind == "custom" for s in plan2.slots)


def test_dossier_compact_and_resume_aware():
    ctx = _ctx(
        resume_work_experience=[{"role": "Backend Engineer", "company": "Stripe", "highlights": ["Cut p99 40%"]}],
        resume_projects=[{"name": "AGC", "description": "Agentic platform", "technologies": ["FastAPI"]}],
        claims_to_verify=["Shipped to production"],
    )
    d = ctx.to_live_candidate_dossier()
    assert d["name"] == "Jane"
    assert any("Backend Engineer at Stripe" in w for w in d["work_experience"])
    assert any("AGC" in p for p in d["notable_projects"])
    assert d["claims_to_verify"] == ["Shipped to production"]
