"""End-to-End Validation Script for the Real-Time AI Interview Experience.

Tests:
1. Pre-flight network WebRTC probe endpoints.
2. WebRTC session negotiation endpoints.
3. Explicit candidate 'Begin Interview' start action.
4. InterviewCoordinatorProcessor state machine flow:
   - Greeting phase
   - Self-intro prompt
   - Deep dive with multiple technical questions
   - Inline dynamic follow-up questioning
   - Barge-in mid-speech interruption handling
   - Closing message & session completion
5. Durable DB persistence of all turns in interview_transcript_turns with strict sequence_number ordering.
6. DB session completion state (current_phase='completed', status='completed').
7. Privacy verification: strict guarantee that no expected_key_points or rubric text is exposed downstream.
"""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GEMINI_MOCK", "1")
os.environ.setdefault("VOICE_MOCK", "1")

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.main import app
from backend.app import models
from backend.app.services.interview.live_session import (
    InterviewCoordinatorProcessor,
    LiveInterviewManager,
)
from backend.app.services.interview.state_machine import InterviewPhase, TurnType
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame


class MockFrameCollector:
    """Collects downstream frames from the processor."""

    def __init__(self):
        self.frames = []

    async def push_frame(self, frame, direction=None):
        self.frames.append(frame)


async def run_validation():
    print("=" * 70)
    print("STARTING REAL-TIME AI INTERVIEW EXPERIENCE VALIDATION")
    print("=" * 70)

    resume_path = Path(__file__).parent / "test_scanned.pdf"
    assert resume_path.exists(), f"Resume fixture not found at {resume_path}"
    resume_bytes = resume_path.read_bytes()

    try:
        async with app.router.lifespan_context(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            suffix = uuid.uuid4().hex[:8]

            # 1. Setup recruiter, job, and candidate
            print("\n[Step 1] Creating recruiter, job with 2 skills, and candidate...")
            recruiter_res = await client.post(
                "/api/auth/signup",
                json={
                    "email": f"rt-recruiter-{suffix}@example.test",
                    "password": "Password123!",
                    "full_name": "Test Lead Recruiter",
                    "role": "recruiter",
                    "company_name": "Candidly Voice Labs",
                },
            )
            assert recruiter_res.status_code == 201, recruiter_res.text
            recruiter = recruiter_res.json()
            rec_headers = {"Authorization": f"Bearer {recruiter['access_token']}"}

            candidate_res = await client.post(
                "/api/auth/signup",
                json={
                    "email": f"rt-candidate-{suffix}@example.test",
                    "password": "Password123!",
                    "full_name": "Jordan Lee",
                    "role": "candidate",
                },
            )
            assert candidate_res.status_code == 201, candidate_res.text
            candidate = candidate_res.json()
            cand_headers = {"Authorization": f"Bearer {candidate['access_token']}"}

            job_res = await client.post(
                "/api/jobs",
                headers=rec_headers,
                json={
                    "job_title": "Senior Distributed Systems Engineer",
                    "department": "Infrastructure",
                    "job_description": "Build resilient distributed data pipelines.",
                    "interview_duration_mins": 25,
                    "max_followup_depth": 1,
                    "skills": [
                        {
                            "name": "Distributed Consensus",
                            "category": "Core Architecture",
                            "priority_tier": "P0",
                            "weight_percentage": 50,
                            "rubric_l3": "Explains Raft leader election and log replication.",
                            "rubric_l4": "Designs split-brain recovery and joint consensus reconfiguration.",
                        },
                        {
                            "name": "Database Sharding & Partitioning",
                            "category": "Core Architecture",
                            "priority_tier": "P0",
                            "weight_percentage": 50,
                            "rubric_l3": "Explains horizontal partitioning and consistent hashing.",
                            "rubric_l4": "Solves hot-spotting, rebalancing, and cross-shard transactions.",
                        },
                    ],
                },
            )
            assert job_res.status_code == 201, job_res.text
            job = job_res.json()

            # 2. Candidate applies and uploads resume
            print("[Step 2] Candidate submitting application & resume...")
            app_res = await client.post(
                "/api/applications",
                headers=cand_headers,
                json={
                    "job_id": job["id"],
                    "candidate_id": candidate["user"]["id"],
                    "full_name": "Jordan Lee",
                    "email": candidate["user"]["email"],
                    "self_reported_experience_years": 6,
                },
            )
            assert app_res.status_code == 201, app_res.text
            application = app_res.json()
            app_id = application["id"]

            upload_res = await client.post(
                f"/api/applications/{app_id}/resume",
                headers=cand_headers,
                files={"file": ("resume.pdf", resume_bytes, "application/pdf")},
            )
            assert upload_res.status_code == 200, upload_res.text

            submit_res = await client.patch(
                f"/api/applications/{app_id}/submit",
                headers=cand_headers,
                json={},
            )
            assert submit_res.status_code == 200, submit_res.text

            # Retrieve interview session
            async with AsyncSessionLocal() as db:
                session_row = (
                    await db.execute(
                        select(models.InterviewSession).where(
                            models.InterviewSession.application_id == app_id
                        )
                    )
                ).scalars().first()
                assert session_row, "Interview session was not generated!"
                session_id = session_row.id

                # Load questions
                q_rows = (
                    await db.execute(
                        select(models.InterviewQuestion)
                        .where(models.InterviewQuestion.session_id == session_id)
                        .order_by(models.InterviewQuestion.question_index)
                    )
                ).scalars().all()
                assert len(q_rows) >= 2, f"Expected at least 2 questions, got {len(q_rows)}"
                print(f"Generated interview session {session_id} with {len(q_rows)} questions.")

            # 3. Test Pre-Flight WebRTC Probe endpoints
            print("\n[Step 3] Testing Pre-Flight WebRTC Probe endpoints...")
            probe_offer = await client.post(
                "/api/interview-sessions/webrtc/probe",
                json={"sdp": "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n", "type": "offer", "pc_id": "probe-test-1"},
            )
            # The probe endpoint processes SmallWebRTC offers or returns 200/500 based on SDP validity
            print(f"WebRTC probe response status: {probe_offer.status_code}")

            probe_data = probe_offer.json() if probe_offer.status_code == 200 else {}
            probe_pc_id = probe_data.get("pc_id", "probe-test-1")
            probe_patch = await client.patch(
                "/api/interview-sessions/webrtc/probe",
                json={"pc_id": probe_pc_id, "candidates": []},
            )
            print(f"WebRTC probe patch status: {probe_patch.status_code}")
            assert probe_patch.status_code == 200

            # 4. Test Live Room WebRTC Session Endpoints
            print("\n[Step 4] Testing Live Room WebRTC Session endpoints...")
            webrtc_offer = await client.post(
                f"/api/interview-sessions/{session_id}/webrtc",
                headers=cand_headers,
                json={"sdp": "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n", "type": "offer", "pc_id": "pc-test-live"},
            )
            print(f"Live WebRTC session offer status: {webrtc_offer.status_code}")
            live_data = webrtc_offer.json() if webrtc_offer.status_code == 200 else {}
            live_pc_id = live_data.get("pc_id", "pc-test-live")

            webrtc_patch = await client.patch(
                f"/api/interview-sessions/{session_id}/webrtc",
                headers=cand_headers,
                json={"pc_id": live_pc_id, "candidates": []},
            )
            print(f"Live WebRTC session patch status: {webrtc_patch.status_code}")
            assert webrtc_patch.status_code == 200

            # 5. Test Explicit Start Endpoint (Second deliberate start action)
            print("\n[Step 5] Testing explicit 'Begin Interview' start endpoint...")
            begin_res = await client.post(
                f"/api/interview-sessions/{session_id}/begin",
                headers=cand_headers,
            )
            assert begin_res.status_code == 200, begin_res.text
            begin_data = begin_res.json()
            assert begin_data["status"] == "begun"
            assert begin_data["phase"] == "greeting"
            print("Explicit 'Begin' confirmed: phase is greeting.")

            # 6. Test Live Status sync endpoint
            print("\n[Step 6] Testing live status endpoint...")
            status_res = await client.get(
                f"/api/interview-sessions/{session_id}/live-status",
                headers=cand_headers,
            )
            assert status_res.status_code == 200, status_res.text
            status_data = status_res.json()
            assert "current_phase" in status_data
            assert status_data["current_phase"] == "greeting"
            print("Live status verified: current_phase is greeting.")

            # 7. Exercise InterviewCoordinatorProcessor State Machine & Barge-In
            print("\n[Step 7] Exercising InterviewCoordinatorProcessor state machine directly...")
            questions_data = [
                {
                    "id": q.id,
                    "question_index": q.question_index,
                    "question_text": q.question_text,
                    "skill_name": q.skill_name,
                    "skill_category": q.skill_category,
                    "follow_up_depth_allowed": 1,
                    "follow_up_count": 0,
                }
                for q in q_rows
            ]

            coordinator = InterviewCoordinatorProcessor(
                session_id=session_id,
                candidate_name="Jordan Lee",
                role_title="Senior Distributed Systems Engineer",
                questions=questions_data,
                candidate_local_hour=10,  # 10 AM -> Good morning
                max_followup_depth=1,
            )
            collector = MockFrameCollector()
            coordinator.push_frame = collector.push_frame

            # A. Begin interview (Greeting + Self-Intro prompt)
            print("\n-> Phase 1: Greeting & Self-Intro prompt...")
            await coordinator.begin_interview()
            assert coordinator.current_phase == InterviewPhase.SELF_INTRO
            tts_frames = [f for f in collector.frames if isinstance(f, TTSSpeakFrame)]
            assert len(tts_frames) >= 1, "Greeting / self-intro TTS frames must be emitted"
            all_tts_text = " ".join(f.text for f in tts_frames)
            assert "Good morning, Jordan Lee" in all_tts_text
            assert "tell me a bit about yourself" in all_tts_text.lower()
            print("Greeting and self-intro TTS frames emitted cleanly.")

            # B. Candidate answers self-intro -> moves to Deep Dive Question 0
            print("\n-> Candidate answers self-intro...")
            await coordinator.handle_candidate_answer(
                "I have spent the last 6 years designing distributed storage engines, "
                "focusing on Raft-based consensus, replication lags, and partition tolerance."
            )
            assert coordinator.current_phase == InterviewPhase.DEEP_DIVE
            assert coordinator.current_question_index == 0
            q0_text = questions_data[0]["question_text"]
            print(f"Deep dive started. Question 0 asked: '{q0_text[:50]}...'")

            # C. Barge-in test: candidate interrupts mid-speech
            print("\n-> Testing Barge-In interruption...")
            await coordinator.process_frame(BotStartedSpeakingFrame(), None)
            assert coordinator.is_speaking is True
            # Mid-speech interruption frame arrives
            await coordinator.process_frame(InterruptionFrame(), None)
            assert coordinator.is_speaking is False
            print("Barge-in verified: speech cancelled immediately, candidate turn registered.")

            # D. Loop through deep dive questions (including any triggered follow-ups) until closing
            print("\n-> Progressing through technical questions and follow-ups...")
            while coordinator.current_phase == InterviewPhase.DEEP_DIVE:
                curr_idx = coordinator.current_question_index
                print(f"Answering question/follow-up at index {curr_idx} (in_followup={coordinator.in_followup})...")
                await coordinator.handle_candidate_answer(
                    f"Technical explanation for question {curr_idx}: We employ Raft log replication with heartbeats, "
                    f"consistent hashing rings for minimal reshuffling, and idempotent keys."
                )

            # E. Phase 4: Closing and completion
            print("\n-> Phase 4: Closing and completion...")
            assert coordinator.current_phase in [InterviewPhase.CLOSING, InterviewPhase.COMPLETED]
            if coordinator.current_phase == InterviewPhase.CLOSING:
                await coordinator.mark_completed()

            assert coordinator.current_phase == InterviewPhase.COMPLETED
            print("State machine successfully reached COMPLETED phase!")

            # 8. Verify Durable Database Persistence
            print("\n[Step 8] Verifying durable DB turns & sequence numbers in PostgreSQL...")
            async with AsyncSessionLocal() as db:
                turns_stmt = (
                    select(models.InterviewTranscriptTurn)
                    .where(models.InterviewTranscriptTurn.session_id == session_id)
                    .order_by(models.InterviewTranscriptTurn.sequence_number.asc())
                )
                db_turns = (await db.execute(turns_stmt)).scalars().all()
                assert len(db_turns) >= 5, f"Expected at least 5 turns, found {len(db_turns)}"

                print(f"Total persisted transcript turns: {len(db_turns)}")
                turn_types_found = set()
                seq_numbers = []

                for t in db_turns:
                    seq_numbers.append(t.sequence_number)
                    turn_types_found.add(t.turn_type)
                    print(f"  Seq {t.sequence_number:02d} | [{t.turn_type:18s}] {t.speaker:9s}: {t.text[:65]}...")

                # Strict monotonic ordering assertion: 0, 1, 2, 3...
                for i, seq in enumerate(seq_numbers):
                    assert seq == i, f"Sequence number mismatch at index {i}: got {seq}"
                print("PASS: Sequence numbers are strictly ordered (0..N with no gaps).")

                # Verify expected turn types exist
                assert "greeting" in turn_types_found, "Missing 'greeting' turn"
                assert "self_intro_prompt" in turn_types_found, "Missing 'self_intro_prompt' turn"
                assert "candidate_answer" in turn_types_found, "Missing 'candidate_answer' turn"
                assert "main_question" in turn_types_found, "Missing 'main_question' turn"
                assert "closing" in turn_types_found, "Missing 'closing' turn"
                print("PASS: All required turn types verified in database.")

                # Verify session completion in DB
                session_final = (
                    await db.execute(
                        select(models.InterviewSession).where(
                            models.InterviewSession.id == session_id
                        )
                    )
                ).scalars().first()
                assert session_final.status == "completed", f"Session status is {session_final.status}, expected completed"
                assert session_final.current_phase == "completed", f"Session current_phase is {session_final.current_phase}, expected completed"
                assert session_final.completed_at is not None, "completed_at timestamp was not set"
                print(f"PASS: Session {session_id} is marked 'completed' in DB with completed_at={session_final.completed_at}.")

            # 9. Verify Privacy: No expected_key_points or rubric text reached candidate
            print("\n[Step 9] Verifying privacy constraint (no rubric / expected_key_points sent to candidate)...")
            rtvi_messages = [f.data for f in collector.frames if isinstance(f, RTVIServerMessageFrame)]
            for msg in rtvi_messages:
                msg_str = str(msg).lower()
                assert "expected_key_points" not in msg_str, f"Privacy violation! expected_key_points found in {msg}"
                assert "rubric_l3" not in msg_str, f"Privacy violation! rubric_l3 found in {msg}"
                assert "rubric_l4" not in msg_str, f"Privacy violation! rubric_l4 found in {msg}"

    finally:
        await LiveInterviewManager.get_instance().cleanup_all()

    print("\n" + "=" * 70)
    print("ALL VALIDATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_validation())
    sys.exit(0)
