"""Comprehensive Test Suite for Checkpoint R2 Interview Blueprint Architecture.

Covers:
1. Server-side approval gate: rejects applications when missing, unapproved, or stale.
2. Staleness detection: marks blueprint stale on job changes, blocks applications until re-approved.
3. Copy-on-write edits: editing an approved blueprint forks to a new draft version.
4. Validator on edits: blocks approval on errors, requires confirmation on warnings.
5. Ownership security: recruiter B cannot view, generate, edit, or approve recruiter A's blueprint (403).
6. Candidate-safe redaction: expectations, probes, triggers, and rubric tiers never reach candidate.
7. Concurrency generation lock: rejects concurrent generation with 409 Conflict.
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal
from backend.app.main import app, _BLUEPRINT_GENERATION_LOCKS
from backend.app.models import (
    User, JobPosting, JobSkill, InterviewBlueprint, BlueprintSection,
    BlueprintExpectation, BlueprintQuestion, JobApplication
)
from backend.app.services.auth import create_access_token, hash_password
from backend.app.services.blueprint.persistence import (
    save_job_blueprint,
    get_job_blueprint,
    approve_job_blueprint,
    compute_job_input_hash,
)


def auth_header(user: User) -> dict:
    token = create_access_token({"sub": user.id, "email": user.email, "role": user.role})
    return {"Authorization": f"Bearer {token}"}


async def run_r2_tests():
    print("=" * 75)
    print("  RUNNING CHECKPOINT R2 BLUEPRINT VERIFICATION SUITE")
    print("=" * 75)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with AsyncSessionLocal() as session:
            # -----------------------------------------------------------------
            # Setup: Create Test Users (Recruiter A, Recruiter B, Candidate)
            # -----------------------------------------------------------------
            print("\n[SETUP] Creating test users in PostgreSQL...")
            recruiter_a = User(
                id=str(uuid.uuid4()),
                email=f"recruiter_a_{uuid.uuid4().hex[:6]}@example.com",
                password_hash=hash_password("Pass123!"),
                role="recruiter",
                full_name="Recruiter Alpha",
            )
            recruiter_b = User(
                id=str(uuid.uuid4()),
                email=f"recruiter_b_{uuid.uuid4().hex[:6]}@example.com",
                password_hash=hash_password("Pass123!"),
                role="recruiter",
                full_name="Recruiter Beta",
            )
            candidate_user = User(
                id=str(uuid.uuid4()),
                email=f"candidate_{uuid.uuid4().hex[:6]}@example.com",
                password_hash=hash_password("Pass123!"),
                role="candidate",
                full_name="Candidate Charlie",
            )
            session.add_all([recruiter_a, recruiter_b, candidate_user])
            await session.commit()
            print("  ✓ Test users created successfully")

            # -----------------------------------------------------------------
            # TEST 1: Server-Side Approval Gate
            # -----------------------------------------------------------------
            print("\n[TEST 1] Server-Side Approval Gate...")

            # 1a. Job with NO blueprint
            job1 = JobPosting(
                id=str(uuid.uuid4()),
                recruiter_id=recruiter_a.id,
                job_title="Systems Engineer - No Blueprint",
                department="Platform",
                seniority_level="Mid-Level (L4)",
                interview_duration_mins=20,
                status="active",
            )
            session.add(job1)
            await session.commit()

            res = await client.post(
                "/api/applications",
                headers=auth_header(candidate_user),
                json={"job_id": job1.id, "full_name": "Charlie", "email": candidate_user.email},
            )
            assert res.status_code == 400, f"Expected 400 for job without blueprint, got {res.status_code}: {res.text}"
            assert "Requires an approved, up-to-date interview blueprint" in res.text
            print("  ✓ Job with no blueprint blocks applications (400 Bad Request)")

            # 1b. Job with DRAFT (unapproved) blueprint
            job2 = JobPosting(
                id=str(uuid.uuid4()),
                recruiter_id=recruiter_a.id,
                job_title="Distributed Systems Lead",
                department="Infrastructure",
                seniority_level="Senior (L5)",
                interview_duration_mins=20,
                status="active",
            )
            session.add(job2)
            await session.flush()

            s1 = JobSkill(job_id=job2.id, name="Distributed Storage", priority_tier="P0", weight_percentage=60.0)
            s2 = JobSkill(job_id=job2.id, name="Consensus Algorithms", priority_tier="P0", weight_percentage=40.0)
            session.add_all([s1, s2])
            await session.commit()

            # Create mock draft blueprint data
            bp_data = {
                "job_id": job2.id,
                "total_duration_mins": 20,
                "active_skill_mins": 14.0,
                "fixed_overhead_mins": 6.0,
                "sections": [
                    {
                        "section_type": "welcome",
                        "title": "Welcome & Rapport",
                        "allocated_minutes": 1.5,
                        "expectations": [],
                        "questions": [],
                    },
                    {
                        "section_type": "skill",
                        "title": "Distributed Storage",
                        "skill_id": s1.id,
                        "skill_name": s1.name,
                        "priority_tier": "P0",
                        "allocated_minutes": 8.0,
                        "target_rubric_tier": "L4-L5 Expert",
                        "expectations": [
                            {"expectation_text": "Designs fault-tolerant replication with quorum reads.", "importance": "core", "source_rubric_level": "L4"},
                            {"expectation_text": "Mitigates split-brain scenarios with fencing tokens.", "importance": "core", "source_rubric_level": "L4"},
                            {"expectation_text": "Optimizes disk write barriers and flush latencies.", "importance": "stretch", "source_rubric_level": "L5"},
                        ],
                        "questions": [
                            {"question_role": "anchor", "question_text": "Walk me through how you designed partition replication in your storage system?", "word_count": 12, "source": "llm"},
                            {"question_role": "anchor_alt", "question_text": "Suppose you were asked to design partition replication from scratch; how would you handle data safety?", "word_count": 16, "source": "llm"},
                            {"question_role": "escalation", "question_text": "How do you handle Byzantine faults across multi-region quorums?", "word_count": 9, "source": "llm"},
                            {"question_role": "probe", "question_text": "What happens if a network split occurs between quorums?", "trigger_condition": "If candidate skips split-brain handling.", "word_count": 9, "source": "llm"},
                            {"question_role": "probe", "question_text": "How do you measure replication lag across lagging follower nodes?", "trigger_condition": "If candidate omits replica telemetry.", "word_count": 10, "source": "llm"},
                            {"question_role": "probe", "question_text": "What disk write barriers or sync strategies do you enforce?", "trigger_condition": "If candidate ignores filesystem durability.", "word_count": 10, "source": "llm"},
                        ],
                    },
                    {
                        "section_type": "skill",
                        "title": "Consensus Algorithms",
                        "skill_id": s2.id,
                        "skill_name": s2.name,
                        "priority_tier": "P0",
                        "allocated_minutes": 6.0,
                        "target_rubric_tier": "L4-L5 Expert",
                        "expectations": [
                            {"expectation_text": "Explains leader election and log compaction mechanics.", "importance": "core", "source_rubric_level": "L4"},
                            {"expectation_text": "Handles partitioned candidate split votes cleanly.", "importance": "core", "source_rubric_level": "L4"},
                            {"expectation_text": "Applies zero-copy serialization during snapshot installations.", "importance": "stretch", "source_rubric_level": "L5"},
                        ],
                        "questions": [
                            {"question_role": "anchor", "question_text": "Walk me through how leader election operates under Raft or Paxos?", "word_count": 11, "source": "llm"},
                            {"question_role": "anchor_alt", "question_text": "Suppose you were asked to implement consensus without Raft; what mechanism would you choose?", "word_count": 14, "source": "llm"},
                            {"question_role": "escalation", "question_text": "How do you prevent log divergence under asymmetric network partitions?", "word_count": 9, "source": "llm"},
                            {"question_role": "probe", "question_text": "What happens when split votes cause repeated term election timeouts?", "trigger_condition": "If candidate ignores randomized election timers.", "word_count": 10, "source": "llm"},
                            {"question_role": "probe", "question_text": "How do you compact logs without stalling active read throughput?", "trigger_condition": "If candidate skips snapshot compaction.", "word_count": 10, "source": "llm"},
                            {"question_role": "probe", "question_text": "How do you prevent stale reads on a deposed leader?", "trigger_condition": "If candidate assumes leader leases never expire.", "word_count": 9, "source": "llm"},
                        ],
                    },
                    {
                        "section_type": "closing",
                        "title": "Candidate Q&A & Close",
                        "allocated_minutes": 4.5,
                        "expectations": [],
                        "questions": [],
                    },
                ],
            }

            saved_bp = await save_job_blueprint(session, bp_data, auto_approve=False)
            job2.active_blueprint_id = saved_bp.id
            await session.commit()

            # Attempt applying to draft blueprint
            res_draft = await client.post(
                "/api/applications",
                headers=auth_header(candidate_user),
                json={"job_id": job2.id, "full_name": "Charlie", "email": candidate_user.email},
            )
            assert res_draft.status_code == 400, f"Expected 400 for draft blueprint, got {res_draft.status_code}"
            print("  ✓ Job with draft (unapproved) blueprint blocks applications (400 Bad Request)")

            # 1c. Approve blueprint -> application succeeds!
            approve_res = await client.post(
                f"/api/jobs/{job2.id}/blueprint/approve",
                headers=auth_header(recruiter_a),
                json={"blueprint_id": saved_bp.id, "confirmed_warnings": True},
            )
            assert approve_res.status_code == 200, f"Approve failed: {approve_res.text}"
            print("  ✓ Blueprint approved by recruiter")

            # Candidate applies now
            res_app = await client.post(
                "/api/applications",
                headers=auth_header(candidate_user),
                json={"job_id": job2.id, "full_name": "Charlie", "email": candidate_user.email},
            )
            assert res_app.status_code == 201, f"Expected 201 after approval, got {res_app.status_code}: {res_app.text}"
            app_data = res_app.json()
            application_id = app_data["id"]
            print(f"  ✓ Candidate application accepted after approval (201 Created, id: {application_id})")

            # Finalize submission succeeds
            res_sub = await client.patch(
                f"/api/applications/{application_id}/submit",
                headers=auth_header(candidate_user),
                json={"full_name": "Charlie Updated"},
            )
            assert res_sub.status_code == 200, f"Expected 200 on submit, got {res_sub.status_code}: {res_sub.text}"
            print("  ✓ Candidate application finalized successfully (200 OK)")

            # -------------------------------------------------------------
            # TEST 2: Staleness Detection
            # -------------------------------------------------------------
            print("\n[TEST 2] Staleness Detection & Invalidation...")

            # Change skill weight on job2 -> modifies input_hash!
            update_job_res = await client.patch(
                f"/api/jobs/{job2.id}",
                headers=auth_header(recruiter_a),
                json={"interview_duration_mins": 30},  # changed duration
            )
            assert update_job_res.status_code == 200
            updated_job_data = update_job_res.json()
            assert updated_job_data["blueprint_is_stale"] is True
            assert updated_job_data["accepts_applications"] is False
            print("  ✓ Job modification triggers staleness: blueprint_is_stale=True, accepts_applications=False")

            # Candidate attempts applying while stale
            res_stale = await client.post(
                "/api/applications",
                headers=auth_header(candidate_user),
                json={"job_id": job2.id, "full_name": "Charlie Stale", "email": candidate_user.email},
            )
            assert res_stale.status_code == 400
            assert "stale and requires recruiter re-approval" in res_stale.text
            print("  ✓ Candidate application blocked while blueprint is stale (400 Bad Request)")

            # Re-approve blueprint to clear staleness
            reapprove_res = await client.post(
                f"/api/jobs/{job2.id}/blueprint/approve",
                headers=auth_header(recruiter_a),
                json={"blueprint_id": saved_bp.id, "confirmed_warnings": True},
            )
            assert reapprove_res.status_code == 200
            reapproved_data = reapprove_res.json()
            assert reapproved_data["is_stale"] is False
            print("  ✓ Re-approval updates input hash and clears staleness: is_stale=False")

            # -------------------------------------------------------------
            # TEST 3: Copy-on-Write Versioning on Edits
            # -------------------------------------------------------------
            print("\n[TEST 3] Copy-on-Write Versioning on Edits...")

            # Current blueprint is approved v1
            get_v1 = await client.get(f"/api/jobs/{job2.id}/blueprint", headers=auth_header(recruiter_a))
            assert get_v1.status_code == 200
            v1_data = get_v1.json()
            assert v1_data["status"] == "approved"
            assert v1_data["version"] == 1

            # Edit section on approved blueprint
            edited_sections = list(v1_data["sections"])
            # Modify expectation in section 1
            edited_sections[1]["expectations"][0]["expectation_text"] = "Enhanced expectation: deep Raft heartbeats."

            put_res = await client.put(
                f"/api/jobs/{job2.id}/blueprint/{v1_data['id']}",
                headers=auth_header(recruiter_a),
                json={"sections": edited_sections},
            )
            assert put_res.status_code == 200, f"Edit failed: {put_res.text}"
            v2_data = put_res.json()

            # Verify that editing created a NEW draft version (v2)
            assert v2_data["version"] == 2, f"Expected version 2, got {v2_data['version']}"
            assert v2_data["status"] == "draft", f"Expected draft status, got {v2_data['status']}"
            assert v2_data["id"] != v1_data["id"], "Expected new blueprint ID for copy-on-write"
            print("  ✓ Editing approved v1 forked to a new draft v2 (Copy-on-Write)")

            # Verify original v1 remains approved in DB
            v1_check = await client.get(f"/api/jobs/{job2.id}/blueprint?version=1", headers=auth_header(recruiter_a))
            assert v1_check.status_code == 200
            assert v1_check.json()["status"] == "approved"
            assert v1_check.json()["version"] == 1
            print("  ✓ Original v1 remains intact with status='approved'")

            # Subsequent edit to draft v2 modifies it IN PLACE
            edited_sections_v2 = list(v2_data["sections"])
            edited_sections_v2[1]["expectations"][0]["expectation_text"] = "Second in-place edit on draft."
            put_v2_res = await client.put(
                f"/api/jobs/{job2.id}/blueprint/{v2_data['id']}",
                headers=auth_header(recruiter_a),
                json={"sections": edited_sections_v2},
            )
            assert put_v2_res.status_code == 200
            v2_updated = put_v2_res.json()
            assert v2_updated["version"] == 2, "Draft edit must not increment version"
            assert v2_updated["id"] == v2_data["id"], "Draft edit must mutate in-place"
            print("  ✓ Subsequent edit to draft v2 mutates in-place (no version increment)")

            # -------------------------------------------------------------
            # TEST 4: Validator on Edits & Approval Gates
            # -------------------------------------------------------------
            print("\n[TEST 4] Validator on Edits & Approval Gates...")

            # 4a. Introduce a fatal error: Remove anchor question completely from section 1
            bad_sections = list(v2_updated["sections"])
            bad_sections[1]["questions"] = [
                q for q in bad_sections[1]["questions"] if q["question_role"] != "anchor"
            ]
            put_bad_res = await client.put(
                f"/api/jobs/{job2.id}/blueprint/{v2_data['id']}",
                headers=auth_header(recruiter_a),
                json={"sections": bad_sections},
            )
            assert put_bad_res.status_code == 200
            bad_data = put_bad_res.json()
            assert len(bad_data["validation_report"]["errors"]) > 0
            print(f"  ✓ Validator correctly surfaces fatal error on missing anchor question: {bad_data['validation_report']['errors']}")

            # Attempt approval with error -> must fail
            approve_err_res = await client.post(
                f"/api/jobs/{job2.id}/blueprint/approve",
                headers=auth_header(recruiter_a),
                json={"blueprint_id": v2_data["id"], "confirmed_warnings": True},
            )
            assert approve_err_res.status_code == 400
            assert "validation errors" in approve_err_res.text
            print("  ✓ Approval gate strictly BLOCKS approval when validation errors exist (400 Bad Request)")

            # 4b. Fix error, but introduce vague skill name ("projects") to test warnings
            fixed_sections = list(bad_data["sections"])
            # Restore anchor question
            fixed_sections[1]["questions"].insert(0, {
                "question_role": "anchor",
                "question_text": "Walk me through how you handled partition replication in production?",
                "word_count": 10,
                "source": "recruiter",
            })
            # Rebalance minutes so total remains 20.0m: 1.5 (welcome) + 6.0 + 5.0 + 3.0 + 4.5 (close) = 20.0m
            fixed_sections[1]["allocated_minutes"] = 6.0
            fixed_sections[2]["allocated_minutes"] = 5.0
            # Add a third skill section with vague name "projects" to test warning without breaking P0 coverage
            fixed_sections.insert(3, {
                "section_type": "skill",
                "title": "projects",
                "skill_name": "projects",
                "priority_tier": "P2",
                "allocated_minutes": 3.0,
                "target_rubric_tier": "L3-L4 Proficient",
                "expectations": [
                    {"expectation_text": "Delivers projects on time with clean commits.", "importance": "core", "source_rubric_level": "L3"},
                    {"expectation_text": "Maintains clear architecture documentation.", "importance": "core", "source_rubric_level": "L3"},
                    {"expectation_text": "Leads post-mortems and incident reviews.", "importance": "stretch", "source_rubric_level": "L4"},
                ],
                "questions": [
                    {"question_role": "anchor", "question_text": "Walk me through how you delivered your most impactful engineering project?", "word_count": 12, "source": "recruiter"},
                    {"question_role": "anchor_alt", "question_text": "Suppose you were asked to deliver a complex project under tight deadlines; how would you approach it?", "word_count": 16, "source": "llm"},
                    {"question_role": "escalation", "question_text": "How did you manage conflicting stakeholder priorities during the project?", "word_count": 10, "source": "llm"},
                    {"question_role": "probe", "question_text": "What project estimation methodology did you employ?", "trigger_condition": "If candidate skips timeline estimation.", "word_count": 7, "source": "llm"},
                    {"question_role": "probe", "question_text": "How did you manage technical debt during delivery?", "trigger_condition": "If candidate skips debt management.", "word_count": 8, "source": "llm"},
                    {"question_role": "probe", "question_text": "What post-launch metrics did you track?", "trigger_condition": "If candidate omits launch monitoring.", "word_count": 6, "source": "llm"},
                ],
            })

            put_warn_res = await client.put(
                f"/api/jobs/{job2.id}/blueprint/{v2_data['id']}",
                headers=auth_header(recruiter_a),
                json={"sections": fixed_sections},
            )
            warn_data = put_warn_res.json()
            print("DEBUG VALIDATION REPORT:", warn_data["validation_report"])
            assert len(warn_data["validation_report"]["errors"]) == 0, f"Unexpected errors: {warn_data['validation_report']['errors']}"
            assert any("projects" in w or "Vague" in w for w in warn_data["validation_report"]["warnings"])
            print("  ✓ Validator surfaces vague skill warning for 'projects'")

            # Attempt approval with confirmed_warnings=False -> must ask for confirmation
            unconfirmed_res = await client.post(
                f"/api/jobs/{job2.id}/blueprint/approve",
                headers=auth_header(recruiter_a),
                json={"blueprint_id": v2_data["id"], "confirmed_warnings": False},
            )
            assert unconfirmed_res.status_code == 400
            assert unconfirmed_res.json()["detail"]["needs_confirmation"] is True
            print("  ✓ Approval rejected when warnings are unconfirmed (needs_confirmation=True)")

            # Approve with confirmed_warnings=True -> SUCCEEDS!
            confirmed_res = await client.post(
                f"/api/jobs/{job2.id}/blueprint/approve",
                headers=auth_header(recruiter_a),
                json={"blueprint_id": v2_data["id"], "confirmed_warnings": True},
            )
            assert confirmed_res.status_code == 200
            v2_approved = confirmed_res.json()
            assert v2_approved["status"] == "approved"
            assert v2_approved["version"] == 2
            print("  ✓ Approval succeeds with confirmed_warnings=True: v2 is now active approved blueprint")

            # -------------------------------------------------------------
            # TEST 5: Ownership Security
            # -------------------------------------------------------------
            print("\n[TEST 5] Ownership Security Enforcement...")

            # Recruiter B tries to access job2 (owned by Recruiter A)
            r_get = await client.get(f"/api/jobs/{job2.id}/blueprint", headers=auth_header(recruiter_b))
            assert r_get.status_code == 403, f"Expected 403, got {r_get.status_code}"

            r_gen = await client.post(f"/api/jobs/{job2.id}/blueprint/generate", headers=auth_header(recruiter_b))
            assert r_gen.status_code == 403, f"Expected 403, got {r_gen.status_code}"

            r_put = await client.put(
                f"/api/jobs/{job2.id}/blueprint/{v2_data['id']}",
                headers=auth_header(recruiter_b),
                json={"sections": []},
            )
            assert r_put.status_code == 403, f"Expected 403, got {r_put.status_code}"

            r_app = await client.post(
                f"/api/jobs/{job2.id}/blueprint/approve",
                headers=auth_header(recruiter_b),
                json={"blueprint_id": v2_data["id"], "confirmed_warnings": True},
            )
            assert r_app.status_code == 403, f"Expected 403, got {r_app.status_code}"

            print("  ✓ Recruiter B access attempts to Recruiter A's blueprint all return 403 Forbidden")

            # -------------------------------------------------------------
            # TEST 6: Candidate-Safe Redaction
            # -------------------------------------------------------------
            print("\n[TEST 6] Candidate-Safe Redaction...")

            # Candidate views blueprint
            cand_res = await client.get(f"/api/jobs/{job2.id}/blueprint", headers=auth_header(candidate_user))
            assert cand_res.status_code == 200
            cand_bp = cand_res.json()

            for sec in cand_bp["sections"]:
                assert sec["expectations"] == [], f"Expectations leaked to candidate: {sec['expectations']}"
                assert sec["target_rubric_tier"] is None, f"Rubric tier leaked to candidate: {sec['target_rubric_tier']}"
                for q in sec["questions"]:
                    assert q["question_role"] != "probe", f"Probe leaked to candidate: {q}"
                    assert q["trigger_condition"] is None, f"Trigger leaked to candidate: {q['trigger_condition']}"
                    assert q["target_expectation_ids"] == [], f"Target expectations leaked: {q['target_expectation_ids']}"

            print("  ✓ Candidate response strictly REDACTED: 0 expectations, 0 probes, 0 triggers, 0 rubric tiers")

            # Recruiter views blueprint -> full data intact
            rec_res = await client.get(f"/api/jobs/{job2.id}/blueprint", headers=auth_header(recruiter_a))
            assert rec_res.status_code == 200
            rec_bp = rec_res.json()
            has_expectations = any(len(s["expectations"]) > 0 for s in rec_bp["sections"])
            has_probes = any(any(q["question_role"] == "probe" for q in s["questions"]) for s in rec_bp["sections"])
            assert has_expectations, "Recruiter must receive full expectations"
            assert has_probes, "Recruiter must receive full probing tree"
            print("  ✓ Recruiter response retains full unredacted expectations and probing tree")

            # -------------------------------------------------------------
            # TEST 7: Concurrency Generation Lock
            # -------------------------------------------------------------
            print("\n[TEST 7] Concurrency Generation Lock...")

            # Acquire lock manually for job2
            if job2.id not in _BLUEPRINT_GENERATION_LOCKS:
                _BLUEPRINT_GENERATION_LOCKS[job2.id] = asyncio.Lock()
            test_lock = _BLUEPRINT_GENERATION_LOCKS[job2.id]

            await test_lock.acquire()
            try:
                # Concurrent generation request
                concur_res = await client.post(
                    f"/api/jobs/{job2.id}/blueprint/generate",
                    headers=auth_header(recruiter_a),
                )
                assert concur_res.status_code == 409, f"Expected 409 Conflict, got {concur_res.status_code}"
                assert "already in progress" in concur_res.text
                print("  ✓ Concurrent blueprint generation strictly returns 409 Conflict")
            finally:
                test_lock.release()

    print("\n" + "=" * 75)
    print("  ALL CHECKPOINT R2 BLUEPRINT VERIFICATION TESTS PASSED (100% GREEN)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run_r2_tests())
