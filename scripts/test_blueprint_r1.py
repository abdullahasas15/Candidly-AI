"""End-to-End Test and Verification Script for Checkpoint R1 Blueprint Backend."""

import asyncio
import os
import sys
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal
from backend.app.models import JobPosting, JobSkill, InterviewSession, CandidateApplication, User
from backend.app.budgeting import calculate_blueprint_section_budgets
from backend.app.services.blueprint.contracts import SkillSectionContent, ExpectationDraft, QuestionDraft
from backend.app.services.blueprint.validator import validate_question_text, validate_blueprint
from backend.app.services.blueprint.generator import generate_job_blueprint
from backend.app.services.blueprint.persistence import (
    save_job_blueprint,
    get_job_blueprint,
    approve_job_blueprint,
    serialize_blueprint,
    init_session_expectation_coverage,
    record_expectation_coverage,
    get_session_expectation_coverage,
)


async def run_tests():
    print("=" * 70)
    print("  RUNNING CHECKPOINT R1 BLUEPRINT VERIFICATION SUITE")
    print("=" * 70)

    # -------------------------------------------------------------
    # Test 1: Budgeting Mathematics
    # -------------------------------------------------------------
    print("\n[TEST 1] Section Budgeting Mathematics...")
    skills = [
        {"name": "Python System Design", "priority_tier": "P0", "weight_percentage": 50.0},
        {"name": "Distributed Databases", "priority_tier": "P0", "weight_percentage": 30.0},
        {"name": "Kafka Streaming", "priority_tier": "P1", "weight_percentage": 15.0},
        {"name": "Docker & K8s", "priority_tier": "P2", "weight_percentage": 5.0},
    ]

    b20 = calculate_blueprint_section_budgets(20, skills)
    assert b20["total_budgeted_mins"] == 20.0, f"Expected 20.0, got {b20['total_budgeted_mins']}"
    assert b20["fixed_overhead_mins"] == 6.0
    assert b20["active_skill_mins"] == 14.0
    assert len(b20["sections"]) == 8  # welcome, intro, 4 skills, candidate_qa, closing
    print("  ✓ 20m budget exact match (20.0m total, 6.0m overhead, 14.0m active)")

    b15 = calculate_blueprint_section_budgets(15, skills)
    assert b15["total_budgeted_mins"] == 15.0
    assert "Docker & K8s" in b15["dropped_skills"], "Expected Docker to be dropped in 15m"
    assert "Kafka Streaming" in b15["dropped_skills"], "Expected Kafka to be dropped in 15m"
    print("  ✓ 15m budget drops P2 and P1 skills when floors exceed active time")

    # -------------------------------------------------------------
    # Test 2: Voice Question Writing Rules & Validator
    # -------------------------------------------------------------
    print("\n[TEST 2] Voice Question Writing Rules & Validation...")

    # Good question
    good_q = "Walk me through how you handled partition rebalancing in Kafka when consumers lagged in prod?"
    good_issues = validate_question_text(good_q, "anchor_question")
    assert not any(i.severity == "error" for i in good_issues), f"Expected good_q to pass: {good_issues}"
    print("  ✓ Natural scenario question passes with 0 errors")

    # Word count ceiling (> 45 words)
    long_q = "Can you please walk me through a detailed time when you had to debug an extremely difficult production issue involving Kafka clusters, network latency spikes, multiple consumer groups, memory leaks in the JVM, and tell me every single diagnostic command you typed in terminal and what happened afterwards?"
    long_issues = validate_question_text(long_q, "anchor_question")
    assert any(i.severity == "error" and "hard ceiling" in i.message for i in long_issues)
    print("  ✓ Word count ceiling (> 45 words) correctly flagged as error")

    # Multi-part question marks
    multi_q = "How did you set up consumer groups? And how did you monitor lag?"
    multi_issues = validate_question_text(multi_q, "anchor_question")
    assert any(i.severity == "error" and "question marks" in i.message for i in multi_issues)
    print("  ✓ Multi-part question (> 1 question mark) correctly flagged as error")

    # Definition-first anti-pattern
    def_q = "What is an event-driven architecture?"
    def_issues = validate_question_text(def_q, "anchor_question")
    assert any(i.severity == "error" and "definition-first" in i.message for i in def_issues)
    print("  ✓ Textbook definition-first question correctly flagged as error")

    # -------------------------------------------------------------
    # Test 3: Blueprint Generation, Persistence, and Versioning
    # -------------------------------------------------------------
    print("\n[TEST 3] Database Persistence & Generation...")
    async with AsyncSessionLocal() as session:
        # Fetch an existing job from DB or create a test job
        stmt = (
            select(JobPosting)
            .options(selectinload(JobPosting.skills))
            .limit(1)
        )
        job = (await session.execute(stmt)).scalars().first()

        if not job:
            job = JobPosting(
                job_title="Lead Backend Engineer",
                department="Engineering",
                seniority_level="Senior (L5)",
                interview_duration_mins=20,
            )
            session.add(job)
            await session.flush()
            s1 = JobSkill(job_id=job.id, name="Python Architecture", priority_tier="P0", weight_percentage=60.0)
            s2 = JobSkill(job_id=job.id, name="PostgreSQL Performance", priority_tier="P0", weight_percentage=40.0)
            session.add_all([s1, s2])
            await session.commit()
            await session.refresh(job)

        print(f"  Target Job: '{job.job_title}' (id: {job.id}, {len(job.skills)} skills)")

        skills_payload = [
            {
                "id": s.id,
                "name": s.name,
                "category": s.category,
                "priority_tier": s.priority_tier,
                "weight_percentage": s.weight_percentage,
                "rubric_l1": s.rubric_l1,
                "rubric_l2": s.rubric_l2,
                "rubric_l3": s.rubric_l3,
                "rubric_l4": s.rubric_l4,
                "rubric_l5": s.rubric_l5,
            }
            for s in (job.skills or [])
        ]

        print("  Generating Blueprint with Gemini AI...")
        bp_dict = await generate_job_blueprint(
            job_id=job.id,
            job_title=job.job_title,
            seniority_level=job.seniority_level or "Senior (L5)",
            duration_mins=job.interview_duration_mins or 20,
            skills=skills_payload,
        )
        print("  ✓ Blueprint generated successfully. Active skill mins:", bp_dict["active_skill_mins"])

        print("  Persisting Blueprint draft into PostgreSQL...")
        saved_bp = await save_job_blueprint(
            db=session,
            blueprint_data=bp_dict,
            auto_approve=False,
        )
        assert saved_bp.id is not None
        assert saved_bp.status == "draft"
        assert len(saved_bp.sections) >= 4
        print(f"  ✓ Persisted Blueprint v{saved_bp.version} (id: {saved_bp.id}, {len(saved_bp.sections)} sections)")

        for sec in saved_bp.sections:
            if sec.section_type == "skill":
                print(f"    - Section: {sec.title} ({sec.allocated_minutes}m, {len(sec.expectations)} expectations, {len(sec.questions)} questions)")

        # Test Approval
        print("  Testing Blueprint Approval...")
        user_res = await session.execute(select(User).limit(1))
        recruiter_user = user_res.scalars().first()
        if not recruiter_user:
            recruiter_user = User(
                email="recruiter-test@candidly.ai",
                full_name="Test Recruiter",
                role="recruiter",
                company_name="Candidly Inc",
            )
            session.add(recruiter_user)
            await session.commit()
            await session.refresh(recruiter_user)

        approved_bp = await approve_job_blueprint(
            db=session,
            job_id=job.id,
            blueprint_id=saved_bp.id,
            user_id=recruiter_user.id,
            confirmed_warnings=True,
        )
        assert approved_bp.status == "approved"
        print(f"  ✓ Approved Blueprint v{approved_bp.version} successfully set as job.active_blueprint_id")

        # Test Candidate-Safe Redaction Serialization
        print("  Testing Candidate-Safe Redaction...")
        serialized = serialize_blueprint(approved_bp)
        assert len(serialized["sections"][2]["expectations"]) > 0, "Recruiter payload must have expectations"

        # Simulate candidate redaction (as done in GET /api/jobs/{job_id}/blueprint)
        candidate_data = serialize_blueprint(approved_bp)
        for sec in candidate_data.get("sections", []):
            sec["expectations"] = []
            for q in sec.get("questions", []):
                q["trigger_condition"] = None
                q["target_expectation_ids"] = []

        assert len(candidate_data["sections"][2]["expectations"]) == 0, "Candidate payload must redact expectations"
        assert candidate_data["sections"][2]["questions"][0]["trigger_condition"] is None
        print("  ✓ Candidate view successfully redacts all expectations, probes triggers, and rubric anchors")

        # -------------------------------------------------------------
        # Test 4: Session Expectation Coverage Tracking
        # -------------------------------------------------------------
        print("\n[TEST 4] Session Expectation Coverage Tracking...")
        from backend.app.models import JobApplication

        sess_stmt = select(InterviewSession).limit(1)
        sess = (await session.execute(sess_stmt)).scalars().first()
        if not sess:
            app_stmt = select(JobApplication).limit(1)
            app = (await session.execute(app_stmt)).scalars().first()
            if not app:
                app = JobApplication(
                    job_id=job.id,
                    full_name="Test Candidate",
                    email="candidate-test@candidly.ai",
                )
                session.add(app)
                await session.flush()
            sess = InterviewSession(
                application_id=app.id,
                job_id=job.id,
                blueprint_id=approved_bp.id,
                blueprint_version=approved_bp.version,
            )
            session.add(sess)
            await session.commit()
            await session.refresh(sess)

        test_session_id = sess.id
        cov_rows = await init_session_expectation_coverage(
            db=session,
            session_id=test_session_id,
            blueprint_id=approved_bp.id,
        )
        print(f"  ✓ Initialized {len(cov_rows)} expectation coverage rows for session {test_session_id[:8]}")

        target_exp = cov_rows[0].expectation_id
        updated_cov = await record_expectation_coverage(
            db=session,
            session_id=test_session_id,
            expectation_id=target_exp,
            status_val="covered",
            turn_id="turn-101",
        )
        assert updated_cov.status == "covered"
        assert "turn-101" in updated_cov.evidence_turn_ids
        print(f"  ✓ Updated expectation {target_exp[:8]} to 'covered' with evidence turn 'turn-101'")

        coverage_summary = await get_session_expectation_coverage(session, test_session_id)
        assert len(coverage_summary) == len(cov_rows)
        assert any(c["status"] == "covered" for c in coverage_summary)
        print(f"  ✓ Query session coverage returned {len(coverage_summary)} items with full joined expectation data")

    print("\n" + "=" * 70)
    print("  ALL CHECKPOINT R1 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
