"""Regression tests for JD-grounded blueprint section generation.

These tests reproduce the compact JSON shape returned by the live provider:
  expectations: [{description, level, stretch}]
  questions: [{kind, question}]
  probes: [{kind, question, trigger_condition, target_expectation_indices}]

The generator must parse that shape, preserve stretch flags, and fail loudly
instead of injecting prewritten placeholder questions.
"""

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
)
from backend.app.services.blueprint.prompts import build_skill_section_user_prompt
from backend.app.services.blueprint.validator import (
    _sanitize_llm_review_issues,
    validate_skill_section,
)


def _compact_provider_payload() -> dict:
    return {
        "expectations": [
            {
                "description": "Understands processes vs threads and can explain the basic differences.",
                "level": 2,
            },
            {
                "description": "Correctly employs synchronization primitives like mutexes and semaphores.",
                "level": 3,
            },
            {
                "description": "Can diagnose simple race conditions and explain TCP/UDP connection handshakes.",
                "level": 3,
            },
            {
                "description": "Can reason about the impact of thread starvation on system performance.",
                "level": 4,
                "stretch": True,
            },
        ],
        "questions": [
            {
                "kind": "anchor",
                "question": "Suppose you receive a stream of data; talk me through the data structures you would choose and their complexity trade-offs.",
            },
            {
                "kind": "anchor_alt",
                "question": "Start simple: how would you count how often each error code appears in a stream?",
            },
            {
                "kind": "escalation",
                "question": "How would you handle unexpected spikes in data volume while maintaining performance?",
            },
        ],
        "probes": [
            {
                "kind": "probe",
                "question": "Which data structure would you choose first, and why?",
                "trigger_condition": "Candidate gives a surface-level answer",
                "target_expectation_indices": [0, 1],
            },
            {
                "kind": "probe",
                "question": "What happens to your approach when the stream is much larger than memory?",
                "trigger_condition": "Candidate ignores memory constraints",
                "target_expectation_indices": [2],
            },
            {
                "kind": "probe",
                "question": "How would you detect and handle duplicate error codes?",
                "trigger_condition": "Candidate does not discuss duplicates",
                "target_expectation_indices": [1],
            },
        ],
    }


def test_compact_provider_shape_is_parsed_without_placeholders():
    content = _normalize_skill_section_data(
        _compact_provider_payload(),
        "Core CS Fundamentals",
        seniority_level="Entry",
    )

    assert content.skill_name == "Core CS Fundamentals"
    assert len(content.expectations) == 4
    assert sum(e.importance == "core" for e in content.expectations) == 3
    assert sum(e.importance == "stretch" for e in content.expectations) == 1
    assert content.expectations[0].source_rubric_level == "L2"
    assert content.expectations[-1].source_rubric_level == "L4"

    assert "data structures you would choose" in content.anchor_question.question_text
    assert content.anchor_alt_question is not None
    assert "each error code" in content.anchor_alt_question.question_text
    assert "unexpected spikes" in content.escalation_question.question_text
    assert len(content.probes) == 3

    all_questions = [
        content.anchor_question.question_text,
        content.anchor_alt_question.question_text,
        content.escalation_question.question_text,
        *(probe.question_text for probe in content.probes),
    ]
    assert not any("How do you handle key engineering challenges" in text for text in all_questions)
    assert not any("What specific trade-offs or constraints did you evaluate" in text for text in all_questions)
    assert all(text.count("?") == 1 for text in all_questions)


def test_missing_required_questions_raise_instead_of_using_generic_fallbacks():
    payload = {
        "expectations": [
            {"description": "Can debug a failing service.", "level": 3},
            {"description": "Explains observability trade-offs.", "level": 4},
        ],
        "questions": [
            {"kind": "anchor", "question": "How would you debug a failing service?"},
        ],
        "probes": [],
    }

    try:
        _normalize_skill_section_data(payload, "Debugging & Testing", seniority_level="Entry")
    except SectionContentError as exc:
        assert any("anchor_alt" in error for error in exc.errors)
        assert any("escalation" in error for error in exc.errors)
        assert any("probes" in error for error in exc.errors)
        serialized = str(exc.payload)
        assert "How do you handle key engineering challenges" not in serialized
        assert "What specific trade-offs or constraints" not in serialized
    else:
        raise AssertionError("Expected SectionContentError for missing required questions")


def test_expectation_caps_reclassify_excess_core_items_without_dropping_text():
    expectations = [
        {
            "expectation_text": f"Expectation {index}",
            "source_rubric_level": f"L{min(index + 2, 5)}",
            "importance": "core",
        }
        for index in range(5)
    ]

    capped = _apply_expectation_caps(expectations)

    assert len(capped) == 5
    assert sum(item["importance"] == "core" for item in capped) == 3
    assert sum(item["importance"] == "stretch" for item in capped) == 2
    assert [item["expectation_text"] for item in capped] == [
        f"Expectation {index}" for index in range(5)
    ]


def test_legacy_canonical_shape_still_parses():
    payload = {
        "skill_name": "API Design",
        "expectations": [
            {
                "expectation_text": "Designs stable API contracts.",
                "source_rubric_level": "L3",
                "importance": "core",
            },
            {
                "expectation_text": "Handles backward compatibility.",
                "source_rubric_level": "L4",
                "importance": "stretch",
            },
        ],
        "anchor_question": {
            "question_role": "anchor",
            "question_text": "How would you version a public API without breaking clients?",
        },
        "anchor_alt_question": {
            "question_role": "anchor_alt",
            "question_text": "Suppose a client only supports the old response shape; how would you keep it working?",
        },
        "escalation_question": {
            "question_role": "escalation",
            "question_text": "How would you migrate thousands of clients across two breaking versions?",
        },
        "probes": [
            {
                "question_role": "probe",
                "question_text": "What contract guarantees would you publish?",
                "trigger_condition": "Candidate gives a vague answer",
                "target_expectation_indices": [0],
            },
            {
                "question_role": "probe",
                "question_text": "How would you detect a breaking change before release?",
                "trigger_condition": "Candidate does not mention compatibility testing",
                "target_expectation_indices": [1],
            },
            {
                "question_role": "probe",
                "question_text": "What would you do when an old client sends an unknown field?",
                "trigger_condition": "Candidate ignores old clients",
                "target_expectation_indices": [0, 1],
            },
        ],
    }

    content = _normalize_skill_section_data(payload, "API Design", seniority_level="Mid")
    issues = validate_skill_section(content, allocated_minutes=6.0, section_index=1, seniority_level="Mid")
    assert not [issue for issue in issues if issue.severity == "error"]


def test_definition_first_and_untriggered_probe_techniques_are_repaired_without_replacement():
    payload = {
        "expectations": [
            {
                "description": "Explains processes and threads and synchronization primitives.",
                "level": 3,
            },
            {
                "description": "Profiles CPU and memory flame graphs to isolate production stalls.",
                "level": 4,
                "stretch": True,
            },
        ],
        "questions": [
            {
                "kind": "anchor",
                "question": "Suppose two threads update a shared counter; how would you prevent a race condition?",
            },
            {
                "kind": "anchor_alt",
                "question": "Start simple: what is a race condition?",
            },
            {
                "kind": "escalation",
                "question": "How would you diagnose a deadlock under heavy load?",
            },
        ],
        "probes": [
            {
                "kind": "probe",
                "question": "What is the difference between a process and a thread?",
                "trigger_condition": "Candidate seems unsure about concurrency basics",
                "target_expectation_indices": [0],
            },
            {
                "kind": "probe",
                "question": "How would you use flame graphs to identify a bottleneck?",
                "trigger_condition": "Candidate discusses performance",
                "target_expectation_indices": [1],
            },
            {
                "kind": "probe",
                "question": "What signals would tell you a mutex is causing contention?",
                "trigger_condition": "Candidate mentions mutexes",
                "target_expectation_indices": [0],
            },
        ],
    }

    content = _normalize_skill_section_data(payload, "Core CS Fundamentals", seniority_level="Entry")
    assert content.probes[0].question_text.startswith("Could you walk me through the difference")
    assert "flame" in (content.probes[1].trigger_condition or "")
    assert "graphs" in (content.probes[1].trigger_condition or "")

    issues = validate_skill_section(content, allocated_minutes=8.0, section_index=1, seniority_level="Entry")
    assert not [issue for issue in issues if issue.severity == "error"]


def test_debugging_prompt_requests_a_failure_scenario_not_a_generic_stream_question():
    prompt = build_skill_section_user_prompt(
        job_title="Software Development Engineer",
        seniority_level="Entry",
        skill_info={
            "name": "Debugging & Testing",
            "category": "Core Technical",
            "priority_tier": "P1",
            "rubrics": {
                "l2": "Writes standard unit tests with mocks.",
                "l3": "Systematically isolates production bugs using APM and logs.",
                "l4": "Profiles CPU/memory flame graphs to isolate production stalls.",
            },
        },
        job_description="Build high-throughput backend microservices and resilient event streaming pipelines.",
    )

    assert "Competency-Specific Scenario Guidance" in prompt
    assert "a service returns stale data after a deploy" in prompt
    assert "never ask them to write code or tests" in prompt


def test_skill_prompt_uses_jd_as_primary_source_and_requests_complete_question_set():
    prompt = build_skill_section_user_prompt(
        job_title="Software Development Engineer",
        seniority_level="Entry",
        skill_info={
            "name": "Data Structures & Problem Solving",
            "category": "Core Technical",
            "priority_tier": "P0",
            "rubrics": {
                "l2": "Struggles with space-time trade-offs.",
                "l3": "Designs clean algorithms.",
                "l4": "Optimizes trade-offs under load.",
            },
        },
        job_description="Build high-throughput backend microservices and resilient event streaming pipelines.",
    )

    assert "PRIMARY SOURCE OF TRUTH" in prompt
    assert "Build high-throughput backend microservices" in prompt
    assert "Do not copy role-template examples verbatim" in prompt
    assert "anchor_alt_question" in prompt
    assert "probes" in prompt
    assert "NEVER return generic placeholders" in prompt


def _review_section_and_skills():
    content = SkillSectionContent(
        skill_name="Data Structures & Problem Solving",
        expectations=[
            ExpectationDraft(
                expectation_text=(
                    "Selects standard collections correctly but struggles with space-time "
                    "trade-offs and edge cases like overflow or off-by-one bounds."
                ),
                source_rubric_level="L2",
                importance="core",
            ),
            ExpectationDraft(
                expectation_text="Designs clean algorithms with verified complexity.",
                source_rubric_level="L3",
                importance="core",
            ),
            ExpectationDraft(
                expectation_text="Optimizes algorithmic trade-offs under heavy load.",
                source_rubric_level="L4",
                importance="stretch",
            ),
        ],
        anchor_question=QuestionDraft(
            question_role="anchor",
            question_text="Suppose you receive a stream of data; talk me through the data structures you would choose and their complexity trade-offs?",
            target_expectation_indices=[0],
        ),
        anchor_alt_question=QuestionDraft(
            question_role="anchor_alt",
            question_text="Start simple: how would you count how often each error code appears in a stream?",
            target_expectation_indices=[0],
        ),
        escalation_question=QuestionDraft(
            question_role="escalation",
            question_text="How would you handle unexpected spikes in data volume while maintaining performance?",
            target_expectation_indices=[2],
        ),
        probes=[
            QuestionDraft(
                question_role="probe",
                question_text="Which data structure would you choose first, and why?",
                trigger_condition="Candidate gives a surface-level answer",
                target_expectation_indices=[0],
            ),
            QuestionDraft(
                question_role="probe",
                question_text="What happens to your approach when the stream is much larger than memory?",
                trigger_condition="Candidate ignores memory constraints",
                target_expectation_indices=[2],
            ),
            QuestionDraft(
                question_role="probe",
                question_text="How would you detect and handle duplicate error codes?",
                trigger_condition="Candidate does not discuss duplicates",
                target_expectation_indices=[1],
            ),
        ],
    )
    sections = [
        {
            "section_type": "skill",
            "skill_name": content.skill_name,
            "content": content,
            "allocated_minutes": 10.0,
        }
    ]
    job_skills = [
        {
            "name": content.skill_name,
            "priority_tier": "P0",
            "rubric_l1": "Fails basic algorithmic analysis.",
            "rubric_l2": (
                "Selects standard collections correctly but struggles with space-time "
                "trade-offs and edge cases like overflow or off-by-one bounds."
            ),
            "rubric_l3": "Designs clean algorithms with verified complexity.",
            "rubric_l4": "Optimizes algorithmic trade-offs under heavy load.",
            "rubric_l5": "Applies hardware-aware structures for low latency.",
        }
    ]
    return content, sections, job_skills


def test_review_false_positives_are_dropped_but_real_violations_survive():
    content, sections, job_skills = _review_section_and_skills()
    review = BatchedBlueprintReviewResponse(
        is_approved=False,
        issues=[
            LLMReviewItem(
                section_index=0,
                skill_name=content.skill_name,
                target_item="expectation_1",
                issue_type="relevance",
                severity="error",
                reason=(
                    "The expectation about struggling with space-time trade-offs and edge cases "
                    "is not strictly related to the skill of Data Structures & Problem Solving."
                ),
            ),
            LLMReviewItem(
                section_index=0,
                skill_name=content.skill_name,
                target_item="probe_1",
                issue_type="technique_leakage",
                severity="error",
                reason="The probe question does not reference any meta-interview framework names.",
            ),
            LLMReviewItem(
                section_index=0,
                skill_name=content.skill_name,
                target_item="expectation_1",
                issue_type="code_request",
                severity="error",
                reason="The expectation mentions writing unit tests with mocks, which is a code-request pattern.",
            ),
            LLMReviewItem(
                section_index=0,
                skill_name=content.skill_name,
                target_item="escalation",
                issue_type="escalation_containment",
                severity="error",
                reason="The escalation question repeats the anchor scenario without pushing depth.",
            ),
        ],
    )

    cleaned = _sanitize_llm_review_issues(review, sections, job_skills)
    assert cleaned.issues == []
    assert cleaned.is_approved is True

    content.probes[0].question_text = "Please answer using the STAR method?"
    review_with_true_positive = BatchedBlueprintReviewResponse(
        is_approved=False,
        issues=[
            LLMReviewItem(
                section_index=0,
                skill_name=content.skill_name,
                target_item="probe_1",
                issue_type="technique_leakage",
                severity="error",
                reason="The probe asks the candidate to use the STAR method.",
            )
        ],
    )
    cleaned_true = _sanitize_llm_review_issues(review_with_true_positive, sections, job_skills)
    assert len(cleaned_true.issues) == 1
    assert cleaned_true.issues[0].issue_type == "technique_leakage"
    assert cleaned_true.is_approved is False
