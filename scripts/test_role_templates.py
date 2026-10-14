#!/usr/bin/env python3
"""Comprehensive test suite for Role Templates, Seniority-Aware Calibration, and Quality Validation."""

import asyncio
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.database import AsyncSessionLocal
from backend.app.services.role_templates import (
    load_role_templates,
    get_all_role_templates,
    get_role_template_by_key,
    extract_template_skills_for_seniority,
)
from backend.app.services.blueprint.validator import (
    check_competency_relevance,
    validate_escalation_self_contained,
    validate_probe_technique_leakage,
    validate_no_code_aloud,
    validate_skill_section,
)
from backend.app.services.blueprint.contracts import (
    SkillSectionContent,
    ExpectationDraft,
    QuestionDraft,
)
from backend.app.services.blueprint.seniority_config import get_seniority_profile


async def test_all():
    print("=================================================================")
    print("Running Role Templates & Blueprint Quality Verification Suite")
    print("=================================================================\n")

    passed_count = 0

    async with AsyncSessionLocal() as session:
        # 1. Idempotent seeding test
        print("Test 1: Idempotent Role Templates Seeding...")
        first_load = await load_role_templates(session)
        assert len(first_load) == 4, f"Expected 4 templates, got {len(first_load)}"
        second_load = await load_role_templates(session)
        assert len(second_load) == 4, f"Expected 4 templates on second load, got {len(second_load)}"
        all_templates = await get_all_role_templates(session)
        assert len(all_templates) == 4, f"Expected 4 active templates, got {len(all_templates)}"
        expected_keys = {"sde", "ai_engineer", "devops", "data_engineer"}
        actual_keys = {t.role_key for t in all_templates}
        assert actual_keys == expected_keys, f"Keys mismatch: {actual_keys} vs {expected_keys}"
        print(f"  ✓ 4 role templates seeded idempotently: {', '.join(sorted(actual_keys))}")
        passed_count += 1

        # 2. Template prefill & weights sum to 100% across all 4 templates x 4 seniorities
        print("\nTest 2: Weights Sum to 100% across all (Template x Seniority) combinations...")
        seniorities = ["entry", "mid", "senior", "lead"]
        for tpl in all_templates:
            for sen in seniorities:
                skills = extract_template_skills_for_seniority(tpl, sen)
                assert len(skills) >= 3, f"{tpl.role_key} {sen} has fewer than 3 skills"
                total_weight = sum(s["weight_percentage"] for s in skills)
                assert abs(total_weight - 100.0) < 0.01, f"{tpl.role_key} {sen} weights sum to {total_weight}, expected 100.0"
        print("  ✓ All 16 combinations (4 templates x 4 seniorities) have weights summing to EXACTLY 100.0%")
        passed_count += 1

        # 3. Seniority level adjustments test
        print("\nTest 3: Seniority Level Calibration Profiles...")
        entry_prof = get_seniority_profile("entry")
        senior_prof = get_seniority_profile("senior")
        assert entry_prof["core_levels"] == ["L2", "L3"], f"Entry core levels mismatch: {entry_prof['core_levels']}"
        assert entry_prof["stretch_levels"] == ["L4"], f"Entry stretch levels mismatch: {entry_prof['stretch_levels']}"
        assert senior_prof["core_levels"] == ["L4"], f"Senior core levels mismatch: {senior_prof['core_levels']}"
        assert senior_prof["stretch_levels"] == ["L5"], f"Senior stretch levels mismatch: {senior_prof['stretch_levels']}"
        print("  ✓ Entry-level: core L2-L3, stretch L4")
        print("  ✓ Senior-level: core L4, stretch L5")
        passed_count += 1

        # 4. Relevance failure on mismatched fixture: Database content under AI Engineering
        print("\nTest 4: Relevance Validator Rejects Contaminated Competencies...")
        mismatched_text = (
            "Explain database indexing internals, B-Tree lookups, multi-version concurrency control (MVCC), "
            "and PostgreSQL write-ahead logging (WAL) under heavy transaction load."
        )
        mismatch_issues = check_competency_relevance(
            skill_name="AI Engineering",
            items=[mismatched_text],
        )
        assert len(mismatch_issues) > 0, "Expected relevance check to FAIL for database content under AI Engineering"
        print(f"  ✓ Contaminated content under 'AI Engineering' correctly rejected: {mismatch_issues[0].message}")
        
        # Conversely, valid AI engineering content must pass
        valid_ai_text = (
            "Design an agentic retrieval pipeline with reciprocal rank fusion, vector embeddings, and chunk reranking."
        )
        valid_issues = check_competency_relevance(
            skill_name="AI Engineering",
            items=[valid_ai_text],
        )
        assert len(valid_issues) == 0, f"Expected valid AI engineering text to pass, got: {valid_issues}"
        print("  ✓ Valid AI Engineering content correctly approved")
        passed_count += 1

        # 5. Probe technique leakage check
        print("\nTest 5: Probe Technique Leakage Validator...")
        leaky_probe = "How would you implement reciprocal rank fusion and vector reranking?"
        empty_trigger = ""
        clean_probe = "What specific trade-off did you make between query latency and index storage overhead?"
        valid_trigger = "Candidate mentions reciprocal rank fusion and vector reranking"
        
        leaky_errs = validate_probe_technique_leakage(
            probe_text=leaky_probe,
            trigger_condition=empty_trigger,
            expectations=["reciprocal rank fusion and vector reranking"],
            probe_role="probe_1",
        )
        assert len(leaky_errs) > 0, "Expected leaky/empty-trigger probe to be flagged"
        
        clean_errs = validate_probe_technique_leakage(
            probe_text=clean_probe,
            trigger_condition=valid_trigger,
            expectations=["reciprocal rank fusion and vector reranking"],
            probe_role="probe_1",
        )
        assert len(clean_errs) == 0, f"Clean probe was unexpectedly flagged: {clean_errs}"
        print(f"  ✓ Leaky probe properly flagged: {leaky_errs[0].message}")
        print("  ✓ Clean behavioral probe passed")
        passed_count += 1

        # 6. Escalation self-contained check
        print("\nTest 6: Escalation Self-Contained Validator...")
        vague_escalation = "Building on your answer above, how would you scale that design?"
        self_contained_escalation = (
            "Suppose your write volume surges by 50x from 2k to 100k events/sec. "
            "Where does your messaging queue saturate first, and what backpressure mechanism prevents consumer OOM?"
        )
        vague_errs = validate_escalation_self_contained(vague_escalation)
        assert len(vague_errs) > 0, "Expected vague escalation to be flagged"
        clean_esc_errs = validate_escalation_self_contained(self_contained_escalation)
        assert len(clean_esc_errs) == 0, f"Self-contained escalation was unexpectedly flagged: {clean_esc_errs}"
        print(f"  ✓ Dependent escalation properly flagged: {vague_errs[0]}")
        print("  ✓ Self-contained scenario escalation passed")
        passed_count += 1

        # 7. Code aloud validator
        print("\nTest 7: No-Code-Aloud Spoken Interview Check...")
        code_aloud_prompt = "Write out the syntax for a merge sort function and speak every bracket and semicolon aloud."
        clean_verbal_prompt = "Walk me through how merge sort divides the input array, and analyze its worst-case memory footprint."
        code_errs = validate_no_code_aloud(code_aloud_prompt)
        assert len(code_errs) > 0, "Expected write code aloud prompt to be flagged"
        clean_code_errs = validate_no_code_aloud(clean_verbal_prompt)
        assert len(clean_code_errs) == 0, f"Clean verbal prompt was unexpectedly flagged: {clean_code_errs}"
        print(f"  ✓ Code-aloud prompt properly flagged: {code_errs[0]}")
        print("  ✓ Verbal conceptual explanation prompt passed")
        passed_count += 1

        # 8. Entry-level hypothetical anchor_alt check
        print("\nTest 8: Entry-Level anchor_alt Presence...")
        sde_tpl = await get_role_template_by_key(session, "sde")
        assert sde_tpl is not None
        skills_entry = extract_template_skills_for_seniority(sde_tpl, "entry")
        first_skill = skills_entry[0]
        assert "target_level_min" in first_skill
        assert first_skill["target_level_min"] == "L2"
        print(f"  ✓ SDE Entry skill '{first_skill['name']}' targets {first_skill['target_level_min']} - {first_skill['target_level_max']}")
        passed_count += 1

        # 9. Batched LLM Review Quality Check (Custom skill not in keyword list)
        print("\nTest 9: Batched LLM Review on Custom Skill Not in Keyword List...")
        from backend.app.services.blueprint.validator import (
            run_batched_blueprint_llm_review,
            validate_blueprint,
        )
        contaminated_k8s_section = {
            "section_type": "skill",
            "skill_name": "Kubernetes Operations",
            "allocated_minutes": 4.0,
            "expectations": [
                {"expectation_text": "Tunes PostgreSQL B-tree indexing and table partitioning", "importance": "core"},
                {"expectation_text": "Configures autovacuum and inspects write-ahead log bloat", "importance": "stretch"},
            ],
            "questions": [
                {
                    "question_role": "anchor",
                    "question_text": "How do you optimize slow query plans in PostgreSQL using composite B-Tree indexes?",
                },
                {
                    "question_role": "escalation",
                    "question_text": "Suppose vacuuming falls behind and causes transaction ID wraparound in Postgres; how do you resolve it?",
                },
                {
                    "question_role": "probe",
                    "question_text": "What EXPLAIN ANALYZE metrics indicate a sequential scan instead of an index scan?",
                    "trigger_condition": "Surface-level answer",
                },
                {
                    "question_role": "probe",
                    "question_text": "How do you tune autovacuum cost limits on high write tables?",
                    "trigger_condition": "Candidate mentions vacuum lag",
                },
                {
                    "question_role": "probe",
                    "question_text": "What trade-offs exist between fillfactor settings and page splits?",
                    "trigger_condition": "Surface-level answer",
                },
            ],
        }

        fixed_welcome = {
            "section_type": "welcome",
            "allocated_minutes": 1.5,
            "welcome_script": "Welcome to the interview.",
        }
        fixed_closing = {
            "section_type": "closing",
            "allocated_minutes": 0.5,
            "closing_script": "Thank you for your time.",
        }

        llm_review = await run_batched_blueprint_llm_review(
            sections=[fixed_welcome, contaminated_k8s_section, fixed_closing],
            seniority_level="mid",
            job_title="DevOps / Infrastructure Engineer",
        )

        assert not llm_review.is_approved or len(llm_review.issues) > 0, "Expected LLM review to flag contaminated Kubernetes section"
        has_relevance_error = any(i.severity == "error" and i.issue_type == "relevance" for i in llm_review.issues)
        assert has_relevance_error, f"Expected a relevance error, got issues: {llm_review.issues}"

        val_report = validate_blueprint(
            sections=[fixed_welcome, contaminated_k8s_section, fixed_closing],
            job_skills=[{"name": "Kubernetes Operations", "priority_tier": "P0"}],
            active_skill_time=4.0,
            total_duration_mins=6,
            seniority_level="mid",
            llm_review=llm_review,
        )
        assert not val_report.is_valid, "ValidationReport should be marked invalid when LLM review has errors"
        print(f"  ✓ Custom skill 'Kubernetes Operations' with PostgreSQL questions correctly flagged: {llm_review.issues[0].reason}")
        print("  ✓ Blueprint validation blocked approval as expected.")
        passed_count += 1

    print("\n=================================================================")
    print(f"All {passed_count}/{passed_count} Tests Passed Successfully!")
    print("=================================================================")


if __name__ == "__main__":
    asyncio.run(test_all())

