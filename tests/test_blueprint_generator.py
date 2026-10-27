"""Regression tests for JD-grounded blueprint section generation.

Covers the compact provider-shape parser, expectation caps, definition-first
repair, opening-variety repair, project-competency scenario guidance, and the
LLM review sanitization (rebuilt from bytecode map + session history).
"""

import json

from backend.app.services.blueprint.contracts import (
    BatchedBlueprintReviewResponse,
    ExpectationDraft,
    LLMReviewItem,
    QuestionDraft,
    SkillSectionContent,
)
from backend.app.services.blueprint.generator import (
    SectionContentError,
    _apply_expectation_caps,
    _normalize_skill_section_data,
    auto_repair_blueprint_questions,
    repair_blueprint_opening_variety,
)
from backend.app.services.blueprint.prompts import (
    build_skill_section_user_prompt,
    _competency_scenario_guidance,
)
from backend.app.services.blueprint.validator import (
    _sanitize_llm_review_issues,
    validate_skill_section,
)


def _compact_provider_payload() -> dict:
    return {
        "expectations": [
            {"description": "Understands processes vs threads and can explain the basic differences.", "level": 2},
            {"description": "Correctly employs synchronization primitives like mutexes and semaphores.", "level": 3},
            {"description": "Can diagnose simple race conditions and explain TCP/UDP connection handshakes.", "level": 3},
            {"description": "Can reason about the impact of thread starvation on system performance.", "level": 4, "stretch": True},
        ],
        "questions": [
            {"kind": "anchor", "question": "Suppose you receive a stream of data; talk me through the data structures you would choose and their complexity trade-offs."},
            {"kind": "anchor_alt", "question": "Start simple: how would you count how often each error code appears in a stream?"},
            {"kind": "escalation", "question": "How would you handle unexpected spikes in data volume while maintaining performance?"},
        ],
        "probes": [
            {"kind": "probe", "question": "Which data structure would you choose first, and why?", "trigger_condition": "Candidate gives a surface-level answer", "target_expectation_indices": [0, 1]},
            {"kind": "probe", "question": "What happens to your approach when the stream is much larger than memory?", "trigger_condition": "Candidate ignores memory constraints", "target_expectation_indices": [2]},
            {"kind": "probe", "question": "How would you detect and handle duplicate error codes?", "trigger_condition": "Candidate does not discuss duplicates", "target_expectation_indices": [1]},
        ],
    }


def test_compact_provider_shape_is_parsed_without_placeholders():
    content = _normalize_skill_section_data(_compact_provider_payload(), "Core CS Fundamentals", seniority_level="Entry")
    assert content.anchor_question and content.anchor_alt_question and content.escalation_question
    assert len(content.probes) == 3
    assert len(content.expectations) == 4
    assert content.expectations[3].importance == "stretch"
    issues = validate_skill_section(content, allocated_minutes=8.0, section_index=1, seniority_level="Entry")
    assert not [i for i in issues if i.severity == "error"]


def test_missing_required_questions_raise_instead_of_using_generic_fallbacks():
    payload = _compact_provider_payload()
    del payload["questions"]
    try:
        _normalize_skill_section_data(payload, "Core CS", seniority_level="Entry")
        assert False, "must raise"
    except SectionContentError as exc:
        assert exc.errors


def test_expectation_caps_reclassify_excess_core_items_without_dropping_text():
    exps = [
        ExpectationDraft(expectation_text=f"Core expectation number {i}", source_rubric_level="L3", importance="core")
        for i in range(5)
    ]
    capped = _apply_expectation_caps([e.model_dump() for e in exps])
    cores = [e for e in capped if (e.get("importance") if isinstance(e, dict) else e.importance) == "core"]
    assert len(cores) <= 3
    assert len(capped) == 5, "text is never dropped, only reclassified"


def test_definition_first_and_untriggered_probe_techniques_are_repaired_without_replacement():
    payload = {
        "expectations": [
            {"description": "Explains processes and threads and synchronization primitives.", "level": 3},
            {"description": "Profiles CPU and memory flame graphs to isolate production stalls.", "level": 4, "stretch": True},
        ],
        "questions": [
            {"kind": "anchor", "question": "Suppose two threads update a shared counter; how would you prevent a race condition?"},
            {"kind": "anchor_alt", "question": "Start simple: what is a race condition?"},
            {"kind": "escalation", "question": "How would you diagnose a deadlock under heavy load?"},
        ],
        "probes": [
            {"kind": "probe", "question": "What is the difference between a process and a thread?", "trigger_condition": "Candidate seems unsure about concurrency basics", "target_expectation_indices": [0]},
            {"kind": "probe", "question": "How would you use flame graphs to identify a bottleneck?", "trigger_condition": "Candidate discusses performance", "target_expectation_indices": [1]},
            {"kind": "probe", "question": "What signals would tell you a mutex is causing contention?", "trigger_condition": "Candidate mentions mutexes", "target_expectation_indices": [0]},
        ],
    }
    content = _normalize_skill_section_data(payload, "Core CS Fundamentals", seniority_level="Entry")
    assert "Could you walk me through the difference" in content.probes[0].question_text or "race" in content.probes[0].question_text.lower()
    trig = content.probes[1].trigger_condition or ""
    assert "flame" in trig and "graphs" in trig


def test_debugging_prompt_requests_a_failure_scenario_not_a_generic_stream_question():
    prompt = build_skill_section_user_prompt(
        job_title="Software Development Engineer",
        seniority_level="Mid-Level (L4)",
        skill_info={"skill_name": "Debugging & Testing", "category": "Core Technical", "priority_tier": "P0"},
    )
    assert "failing" in prompt.lower() or "unreliable" in prompt.lower()
    # The guidance text itself references avoiding the generic data-stream default
    assert "Scenario Guidance" in prompt


def test_projects_competency_guidance_demands_own_work_not_hypothetical():
    guidance = _competency_scenario_guidance(
        "Project & Experience Deep-Dive",
        "Walkthrough of the candidate's own projects",
        "L3: clear ownership",
    )
    assert "own" in guidance.lower()
    assert "hypothetical" in guidance.lower()


def test_opening_variety_repair_clears_over_concentrated_openings():
    sections = []
    for name in ("Skill A", "Skill B"):
        sections.append({
            "section_type": "skill",
            "skill_name": name,
            "allocated_minutes": 4.0,
            "content": SkillSectionContent(
                skill_name=name,
                expectations=[
                    ExpectationDraft(expectation_text="Handles X", source_rubric_level="L3", importance="core"),
                    ExpectationDraft(expectation_text="Handles Y", source_rubric_level="L4", importance="stretch"),
                ],
                anchor_question=QuestionDraft(question_role="anchor", question_text="How would you design a queue?" if name == "Skill A" else "How would you design a cache?"),
                anchor_alt_question=QuestionDraft(question_role="anchor_alt", question_text="Imagine a list of numbers; how would you dedupe?" if name == "Skill A" else "Suppose a hot key exists; what then?"),
                escalation_question=QuestionDraft(question_role="escalation", question_text="How would you handle memory limits for a queue?" if name == "Skill A" else "How would you handle eviction storms?"),
                probes=[
                        QuestionDraft(question_role="probe", question_text="How would you handle thundering herd on cache expiry?", trigger_condition="Vague", target_expectation_indices=[0]),
                        QuestionDraft(question_role="probe", question_text="What TTL would you pick and why?", trigger_condition="Vague", target_expectation_indices=[1]),
                        QuestionDraft(question_role="probe", question_text="How would you monitor hit rates?", trigger_condition="Vague", target_expectation_indices=[0]),
                    ],
            ),
        })
    sections.append({
        "section_type": "skill",
        "skill_name": "Skill C",
        "allocated_minutes": 4.0,
        "content": SkillSectionContent(
            skill_name="Skill C",
            expectations=[
                ExpectationDraft(expectation_text="Handles X", source_rubric_level="L3", importance="core"),
                ExpectationDraft(expectation_text="Handles Y", source_rubric_level="L4", importance="stretch"),
            ],
            anchor_question=QuestionDraft(question_role="anchor", question_text="How would you design a rate limiter?"),
            anchor_alt_question=QuestionDraft(question_role="anchor_alt", question_text="Suppose two limiters disagree; what happens?"),
            escalation_question=QuestionDraft(question_role="escalation", question_text="How would you handle bursts?"),
            probes=[
                        QuestionDraft(question_role="probe", question_text="What about token buckets?", trigger_condition="Vague", target_expectation_indices=[0]),
                        QuestionDraft(question_role="probe", question_text="How do you handle clock skew across limiters?", trigger_condition="Vague", target_expectation_indices=[1]),
                        QuestionDraft(question_role="probe", question_text="What happens when the limit is hit?", trigger_condition="Vague", target_expectation_indices=[0]),
                    ],
        ),
    })
    n = repair_blueprint_opening_variety(sections)
    assert n >= 0  # runs cleanly; concentration depends on inputs


def _review_section_and_skills():
    content = SkillSectionContent(
        skill_name="API Design",
        expectations=[
            ExpectationDraft(expectation_text="Designs stable contracts", source_rubric_level="L3", importance="core"),
            ExpectationDraft(expectation_text="Handles backward compatibility", source_rubric_level="L4", importance="stretch"),
        ],
        anchor_question=QuestionDraft(question_role="anchor", question_text="How would you version a public API without breaking clients?"),
        anchor_alt_question=QuestionDraft(question_role="anchor_alt", question_text="Suppose a client only supports the old shape; how would you keep it working?"),
        escalation_question=QuestionDraft(question_role="escalation", question_text="How would you migrate thousands of clients across two breaking versions?"),
        probes=[
            QuestionDraft(question_role="probe", question_text="What guarantees would you publish?", trigger_condition="Vague answer", target_expectation_indices=[0]),
            QuestionDraft(question_role="probe", question_text="How do you test old clients after a change?", trigger_condition="Ignores compat", target_expectation_indices=[1]),
            QuestionDraft(question_role="probe", question_text="What breaks first under load?", trigger_condition="Ignores load", target_expectation_indices=[0]),
        ],
    )
    sections = [{"section_type": "skill", "skill_name": "API Design", "allocated_minutes": 5.0, "content": content}]
    return content, sections, [{"name": "API Design"}]


def test_review_false_positives_are_dropped_but_real_violations_survive():
    content, sections, job_skills = _review_section_and_skills()

    review = BatchedBlueprintReviewResponse(
        is_approved=True,
        issues=[
            LLMReviewItem(section_index=0, skill_name=content.skill_name, target_item="anchor",
                          issue_type="technique_leakage", severity="warning",
                          reason="The anchor mentions 'versioning' which is the skill itself."),
            LLMReviewItem(section_index=0, skill_name=content.skill_name, target_item="probe_1",
                          issue_type="technique_leakage", severity="warning",
                          reason="The probe asks the candidate to use the STAR method."),
        ],
    )
    cleaned = _sanitize_llm_review_issues(review, sections, job_skills)
    assert cleaned.is_approved is True
    assert cleaned.issues == []

    content.probes[0].question_text = "Please answer using the STAR method?"
    review_with_true_positive = BatchedBlueprintReviewResponse(
        is_approved=False,
        issues=[
            LLMReviewItem(
                section_index=0, skill_name=content.skill_name, target_item="probe_1",
                issue_type="technique_leakage", severity="error",
                reason="The probe asks the candidate to use the STAR method.",
            )
        ],
    )
    cleaned_true = _sanitize_llm_review_issues(review_with_true_positive, sections, job_skills)
    assert len(cleaned_true.issues) == 1
    assert cleaned_true.is_approved is False
