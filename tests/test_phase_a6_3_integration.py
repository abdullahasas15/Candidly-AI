"""Phase A6.3 Integration Test Suite.

Verifies end-to-end integration fixes:
1. Candidate Room Startup Handshake:
   - Bounded client_ready handshake requirement before greeting emission.
   - Flux STT failure handling without hanging or reporting false live session.
   - Session validation and eager loading without lazy loading exceptions.
2. End Interview Lifecycle:
   - WebSocket on_end_button produces terminal SessionEnded event with request_id.
   - REST endpoint caller authorization (candidate/recruiter/admin vs unauthorized).
   - REST endpoint idempotency and runner cleanup in ACTIVE_RUNNERS.
3. Recruiter Blueprint Security & Approval Consistency:
   - Authenticated recruiter vs unauthenticated candidate redaction.
   - Invalid token surfaces 401 Unauthorized.
   - Blueprint approval blocked when validation report contains errors.
   - Application submission blocked when job blueprint has unresolved validation errors.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal, engine
from backend.app.main import (
    app,
    _enrich_jobs_with_blueprint_status,
)


@pytest.fixture(autouse=True)
def cleanup_db_engine_after_test():
    yield
    engine.sync_engine.dispose()
from backend.app.models import (
    BlueprintExpectation,
    BlueprintQuestion,
    BlueprintSection,
    InterviewBlueprint,
    InterviewEvaluation,
    InterviewQuestion,
    InterviewSession,
    JobApplication,
    JobPosting,
    JobSkill,
    User,
)
from backend.app.services.interview_v2.finalizer import finalize_interview_session
from backend.app.services.auth import create_access_token, decode_access_token
from backend.app.services.interview_v2.conductor import (
    ConductorPhase,
    ConductorState,
    EndButton,
    SessionStart,
)
from backend.app.services.interview_v2.router import (
    ACTIVE_RUNNERS,
    ws_interview_endpoint,
)
from backend.app.services.interview_v2.runner import (
    SessionRunner,
    build_script,
    load_real_session_script,
)
from backend.app.services.blueprint.persistence import (
    approve_job_blueprint,
    update_or_fork_job_blueprint,
)
from backend.app.services.blueprint.validator import validate_blueprint


class FakeWebSocket:
    """Mock WebSocket for testing interview protocol exchanges."""

    def __init__(self, incoming_messages: Optional[List[Dict[str, Any]]] = None):
        self.sent_messages: List[Dict[str, Any]] = []
        self.sent_bytes: List[bytes] = []
        self._incoming = list(incoming_messages or [])
        self.closed = False
        self.close_code: Optional[int] = None
        self.close_reason: Optional[str] = None

    async def accept(self) -> None:
        pass

    async def receive(self) -> Dict[str, Any]:
        if self._incoming:
            item = self._incoming.pop(0)
            if isinstance(item, dict):
                return {"type": "websocket.receive", "text": json.dumps(item)}
            return {"type": "websocket.receive", "text": str(item)}
        await asyncio.sleep(100)
        return {"type": "websocket.disconnect"}

    async def receive_json(self) -> Dict[str, Any]:
        if self._incoming:
            return self._incoming.pop(0)
        await asyncio.sleep(10)
        return {"type": "ping"}

    async def receive_text(self) -> str:
        msg = await self.receive_json()
        return json.dumps(msg)

    async def send_json(self, data: Dict[str, Any]) -> None:
        self.sent_messages.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class FakeTTS:
    def __init__(self):
        self.calls: List[str] = []
        self.cancelled = False
        self.voice = "aura-2-mock"

    async def speak(self, text: str) -> AsyncIterator[bytes]:
        self.calls.append(text)
        yield b"\x00\x01" * 240

    async def cancel(self) -> None:
        self.cancelled = True


def make_sample_script() -> Dict[str, Any]:
    return {
        "questions": [
            {
                "question_index": 0,
                "kind": "welcome",
                "skill_name": "Welcome",
                "question_text": "Hello, welcome to your Candidly interview!",
                "priority_tier": "P0",
            },
            {
                "question_index": 1,
                "kind": "anchor",
                "skill_name": "Data Structures",
                "question_text": "How do you implement a priority queue?",
                "priority_tier": "P0",
            },
        ]
    }


# =============================================================================
# 1. Candidate Startup Handshake Tests
# =============================================================================

@pytest.mark.asyncio
async def test_handshake_client_ready_triggers_runner_start():
    """Verify runner.start() is only triggered after client_ready is received."""
    ws = FakeWebSocket(incoming_messages=[{"type": "client_ready", "sample_rate": 24000}])
    fake_tts = FakeTTS()
    script = make_sample_script()

    runner = SessionRunner(
        session_id="test-session-handshake-1",
        websocket=ws,
        flux_client=None,
        aura_client=fake_tts,
        script=script,
    )

    # Initial state before start is idle/empty
    assert runner.running is False

    # Simulate router receiving client_ready
    msg = await ws.receive_json()
    assert msg.get("type") == "client_ready"

    # Start runner
    await runner.start()
    assert runner.running is True

    # Allow event loop to process SessionStart effect and transition to WELCOME
    await asyncio.sleep(0.05)
    assert runner.state.phase == ConductorPhase.WELCOME

    # Wait for welcome breather (0.15s) and effect loop execution
    await asyncio.sleep(0.20)
    assert len(fake_tts.calls) > 0
    assert "Hello, welcome" in fake_tts.calls[0]

    await runner.stop()


@pytest.mark.asyncio
async def test_handshake_timeout_handling():
    """Verify router timeout when client fails to send client_ready."""
    ws = FakeWebSocket(incoming_messages=[])  # Empty queue will timeout

    mock_session = MagicMock()
    mock_session.id = "test-timeout-session"
    mock_session.job_id = "job-1"
    mock_session.application = MagicMock(candidate_id="cand-timeout", email="cand@test.com")
    mock_session.job = MagicMock(recruiter_id="rec-1")
    ticket = create_access_token({"sub": "cand-timeout", "email": "cand@test.com", "role": "candidate", "session_id": mock_session.id})

    with patch("backend.app.services.interview_v2.router.load_real_session_script", return_value=(mock_session, make_sample_script())):
        with patch("backend.app.services.interview_v2.router.FluxSTTClient") as mock_flux_cls:
            mock_flux = AsyncMock()
            mock_flux_cls.return_value = mock_flux
            with patch("backend.app.services.interview_v2.router.AuraTTSClient"):
                with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                    await ws_interview_endpoint(ws, "test-timeout-session", ticket=ticket)

                # Verify SessionError and socket closure
                error_msgs = [m for m in ws.sent_messages if m.get("type") == "SessionError"]
                assert len(error_msgs) == 1
                assert error_msgs[0]["error"] == "HandshakeTimeout"
                assert "timed out" in error_msgs[0]["detail"]
                assert ws.closed is True
                assert ws.close_code == 4008


@pytest.mark.asyncio
async def test_flux_initialization_failure_clean_exit():
    """Verify that Flux STT initialization failure produces SessionError 4003 and doesn't run."""
    ws = FakeWebSocket()
    mock_session = MagicMock()
    mock_session.id = "test-flux-fail"
    mock_session.application = MagicMock(candidate_id="cand-flux", email="cand@test.com")
    mock_session.job = MagicMock(recruiter_id="rec-1")
    ticket = create_access_token({"sub": "cand-flux", "email": "cand@test.com", "role": "candidate", "session_id": mock_session.id})

    with patch("backend.app.services.interview_v2.router.load_real_session_script", return_value=(mock_session, make_sample_script())):
        with patch("backend.app.services.interview_v2.router.FluxSTTClient") as mock_flux_cls:
            mock_flux = MagicMock()
            mock_flux.start = AsyncMock(side_effect=RuntimeError("Flux connection failed"))
            mock_flux_cls.return_value = mock_flux
            with patch("backend.app.services.interview_v2.router.AuraTTSClient"):
                await ws_interview_endpoint(ws, "test-flux-fail", ticket=ticket)

                error_msgs = [m for m in ws.sent_messages if m.get("type") == "SessionError"]
                assert len(error_msgs) == 1
                assert error_msgs[0]["error"] == "STTInitializationFailed"
                assert ws.closed is True
                assert ws.close_code == 4003


@pytest.mark.asyncio
async def test_p0_4_websocket_authentication_ownership_and_incumbent_runner_protection():
    """Verify WebSocket authentication (4401 on missing/invalid, 4403 on wrong owner),
    incumbent runner protection against eviction, and successful connection with ticket."""
    session_id = "test-auth-session-uuid"
    mock_session = MagicMock()
    mock_session.id = session_id
    mock_session.job_id = "job-auth-1"
    mock_session.application = MagicMock(candidate_id="candidate-owner-1", email="candidate@test.com")
    mock_session.job = MagicMock(recruiter_id="recruiter-owner-1")

    # 1. Missing ticket -> 4401
    ws_no_ticket = FakeWebSocket()
    with patch("backend.app.services.interview_v2.router.load_real_session_script", return_value=(mock_session, make_sample_script())):
        await ws_interview_endpoint(ws_no_ticket, session_id, ticket=None)
        assert ws_no_ticket.closed is True
        assert ws_no_ticket.close_code == 4401

    # 2. Invalid ticket string -> 4401
    ws_invalid_ticket = FakeWebSocket()
    with patch("backend.app.services.interview_v2.router.load_real_session_script", return_value=(mock_session, make_sample_script())):
        await ws_interview_endpoint(ws_invalid_ticket, session_id, ticket="invalid.garbage.jwt")
        assert ws_invalid_ticket.closed is True
        assert ws_invalid_ticket.close_code == 4401

    # 3. Unauthorized user's ticket (attacker with valid JWT for different user) -> 4403
    attacker_ticket = create_access_token({
        "sub": "attacker-user-999",
        "email": "attacker@evil.com",
        "role": "candidate",
        "session_id": session_id,
    })
    ws_attacker = FakeWebSocket()

    # Place an incumbent runner in ACTIVE_RUNNERS
    mock_incumbent_runner = MagicMock()
    mock_incumbent_runner.stop = AsyncMock()
    ACTIVE_RUNNERS[session_id] = mock_incumbent_runner

    with patch("backend.app.services.interview_v2.router.load_real_session_script", return_value=(mock_session, make_sample_script())):
        await ws_interview_endpoint(ws_attacker, session_id, ticket=attacker_ticket)
        assert ws_attacker.closed is True
        assert ws_attacker.close_code == 4403

        # Incumbent runner MUST NOT be evicted or stopped by unauthorized connection!
        assert session_id in ACTIVE_RUNNERS
        assert ACTIVE_RUNNERS[session_id] is mock_incumbent_runner
        mock_incumbent_runner.stop.assert_not_called()

    # 4. Valid ticket for authorized candidate -> SessionConnected and displaces runner
    valid_ticket = create_access_token({
        "sub": "candidate-owner-1",
        "email": "candidate@test.com",
        "role": "candidate",
        "session_id": session_id,
    })
    ws_valid = FakeWebSocket(incoming_messages=[{"type": "client_ready", "sample_rate": 24000}])

    with patch("backend.app.services.interview_v2.router.load_real_session_script", return_value=(mock_session, make_sample_script())):
        with patch("backend.app.services.interview_v2.router.FluxSTTClient") as mock_flux_cls:
            mock_flux = AsyncMock()
            mock_flux_cls.return_value = mock_flux
            with patch("backend.app.services.interview_v2.router.AuraTTSClient"):
                # Run connection in background task and cancel after handshake
                endpoint_task = asyncio.create_task(
                    ws_interview_endpoint(ws_valid, session_id, ticket=valid_ticket)
                )
                await asyncio.sleep(0.05)

                # Incumbent runner was stopped and evicted
                mock_incumbent_runner.stop.assert_awaited_once()

                # Client received SessionConnected
                connected_events = [m for m in ws_valid.sent_messages if m.get("type") == "SessionConnected"]
                assert len(connected_events) == 1
                assert connected_events[0]["session_id"] == session_id

                endpoint_task.cancel()
                try:
                    await endpoint_task
                except asyncio.CancelledError:
                    pass

    # Clean up ACTIVE_RUNNERS
    ACTIVE_RUNNERS.pop(session_id, None)


@pytest.mark.asyncio
async def test_p0_4_ws_ticket_endpoint_generation_and_authorization():
    """Verify POST /api/interview-sessions/{id}/ws-ticket endpoint authorization and ticket issuance."""
    async with AsyncSessionLocal() as db:
        now_ts = datetime.now(timezone.utc).timestamp()
        candidate = User(
            email=f"candidate_ticket_{now_ts}@example.com",
            full_name="Candidate Ticket",
            role="candidate",
            password_hash="pw",
        )
        unauthorized_user = User(
            email=f"other_ticket_{now_ts}@example.com",
            full_name="Other Ticket",
            role="candidate",
            password_hash="pw",
        )
        recruiter = User(
            email=f"recruiter_ticket_{now_ts}@example.com",
            full_name="Recruiter Ticket",
            role="recruiter",
            password_hash="pw",
        )
        db.add_all([candidate, unauthorized_user, recruiter])
        await db.flush()

        job = JobPosting(
            job_title="Security Engineer",
            department="Engineering",
            recruiter_id=recruiter.id,
            status="active",
        )
        db.add(job)
        await db.flush()

        app_record = JobApplication(
            job_id=job.id,
            candidate_id=candidate.id,
            full_name=candidate.full_name,
            email=candidate.email,
            status="interview_ready",
        )
        db.add(app_record)
        await db.flush()

        session = InterviewSession(
            application_id=app_record.id,
            job_id=job.id,
            status="in_progress",
            current_phase="greeting",
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    token_candidate = create_access_token({"sub": candidate.id, "email": candidate.email, "role": "candidate", "id": candidate.id})
    token_unauth = create_access_token({"sub": unauthorized_user.id, "email": unauthorized_user.email, "role": "candidate", "id": unauthorized_user.id})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Unauthenticated -> 401
        res_no_auth = await client.post(f"/api/interview-sessions/{session_id}/ws-ticket")
        assert res_no_auth.status_code == 401

        # 2. Unauthorized user -> 403
        res_forbidden = await client.post(
            f"/api/interview-sessions/{session_id}/ws-ticket",
            headers={"Authorization": f"Bearer {token_unauth}"},
        )
        assert res_forbidden.status_code == 403

        # 3. Authorized candidate -> 200 with valid ticket bound to session
        res_ok = await client.post(
            f"/api/interview-sessions/{session_id}/ws-ticket",
            headers={"Authorization": f"Bearer {token_candidate}"},
        )
        assert res_ok.status_code == 200
        ticket_data = res_ok.json()
        assert "ticket" in ticket_data
        assert ticket_data["session_id"] == session_id
        assert ticket_data["expires_in"] == 300

        # Verify decoded ticket claims
        claims = decode_access_token(ticket_data["ticket"])
        assert claims["sub"] == candidate.id
        assert claims["session_id"] == session_id
        assert claims["type"] == "ws_ticket"


@pytest.mark.asyncio
async def test_tts_synthesis_failure_recovers_to_listening():
    """Verify that when Aura-2 synthesis fails, TTSError is emitted and conductor does not get stuck in SPEAKING."""
    ws = FakeWebSocket()

    class FailingTTS:
        voice = "failing-voice"

        async def speak(self, text: str) -> AsyncIterator[bytes]:
            raise RuntimeError("TTS upstream service unavailable")
            yield b""  # unreachable

        async def cancel(self) -> None:
            pass

    runner = SessionRunner(
        session_id="test-tts-fail-session",
        websocket=ws,
        flux_client=None,
        aura_client=FailingTTS(),
        script=make_sample_script(),
    )

    await runner.start()
    # Allow runner loop to process welcome breather (0.15s) and hit TTS error
    await asyncio.sleep(0.25)

    # TTSError must have been emitted to frontend
    tts_errors = [m for m in ws.sent_messages if m.get("type") == "TTSError"]
    assert len(tts_errors) > 0

    # Runner state must not be stuck speaking
    assert runner.state.bot_speaking is False

    await runner.stop()


# =============================================================================
# 2. End Interview Lifecycle Tests
# =============================================================================

@pytest.mark.asyncio
async def test_runner_on_end_button_produces_session_ended_event():
    """Verify that runner on_end_button emits SessionEnding first, then SessionEnded upon playback completion."""
    ws = FakeWebSocket()
    tts = FakeTTS()
    runner = SessionRunner(
        session_id="test-end-req-1",
        websocket=ws,
        flux_client=None,
        aura_client=tts,
        script=make_sample_script(),
    )

    with patch("backend.app.services.interview_v2.runner.AsyncSessionLocal") as mock_db_cls:
        mock_db = AsyncMock()
        mock_db_cls.return_value.__aenter__.return_value = mock_db
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        await runner.start()
        await asyncio.sleep(0.05)

        # Candidate clicks End Interview with client request_id
        await runner.on_end_button(request_id="req-uuid-999")
        await asyncio.sleep(0.05)

        # 1. Verify SessionEnding event was emitted first, not SessionEnded
        ending_events = [m for m in ws.sent_messages if m.get("type") == "SessionEnding"]
        assert len(ending_events) == 1
        assert ending_events[0]["session_id"] == "test-end-req-1"
        assert ending_events[0]["request_id"] == "req-uuid-999"
        assert ending_events[0]["status"] == "ending"
        assert runner.state.phase == ConductorPhase.CLOSING

        # SessionEnded must NOT be emitted while closing audio is still streaming/playing
        assert not any(m.get("type") == "SessionEnded" for m in ws.sent_messages)

        # 2. Client finishes playback and reports playback_ended
        await runner.on_playback_ended(runner.state.active_speech_id)
        await asyncio.sleep(0.05)

        # Verify terminal WebSocket event
        end_events = [m for m in ws.sent_messages if m.get("type") == "SessionEnded"]
        assert len(end_events) == 1
        assert end_events[0]["session_id"] == "test-end-req-1"
        assert end_events[0]["request_id"] == "req-uuid-999"
        assert end_events[0]["status"] == "completed"

        assert runner.state.phase == ConductorPhase.COMPLETED

        await runner.stop()


@pytest.mark.asyncio
async def test_p1_9_closing_speech_timeout_fallback():
    """Verify that if client fails to send playback_ended, conductor 12s timeout finalizes and sends SessionEnded."""
    ws = FakeWebSocket()
    tts = FakeTTS()
    runner = SessionRunner(
        session_id="test-end-timeout-1",
        websocket=ws,
        flux_client=None,
        aura_client=tts,
        script=make_sample_script(),
    )

    with patch("backend.app.services.interview_v2.runner.AsyncSessionLocal") as mock_db_cls:
        mock_db = AsyncMock()
        mock_db_cls.return_value.__aenter__.return_value = mock_db
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        await runner.start()
        await asyncio.sleep(0.05)

        await runner.on_end_button(request_id="req-timeout-1")
        await asyncio.sleep(0.05)

        assert runner.state.phase == ConductorPhase.CLOSING
        assert any(m.get("type") == "SessionEnding" for m in ws.sent_messages)
        assert not any(m.get("type") == "SessionEnded" for m in ws.sent_messages)

        # Advance tick past 12s timeout
        now = runner.now_ms() + 13000
        from backend.app.services.interview_v2.conductor import Tick
        await runner.queue.put(Tick(now_ms=now))
        await asyncio.sleep(0.05)

        assert runner.state.phase == ConductorPhase.COMPLETED
        assert any(m.get("type") == "SessionEnded" for m in ws.sent_messages)

        await runner.stop()


def test_p1_12_build_script_job_facts_model_mapping():
    """Verify that build_script correctly maps JobPosting fields and JobSkill objects into candidate Q&A facts."""
    class MockSkill:
        def __init__(self, name):
            self.name = name

    class MockJob:
        def __init__(self):
            self.job_title = "Senior Distributed Systems Engineer"
            self.job_description = "Design and maintain high-throughput streaming systems using Kafka and Redis."
            self.seniority_level = "senior"
            self.skills = [MockSkill("Distributed Systems"), MockSkill("Python"), MockSkill("FastAPI")]

    class MockSession:
        def __init__(self):
            self.id = "sess-qa-facts"
            self.job = MockJob()
            self.blueprint = None
            self.questions = []

    mock_session = MockSession()
    script = build_script(mock_session)
    job_record = script.get("job_record", {})

    assert job_record["title"] == "Senior Distributed Systems Engineer"
    assert job_record["description"] == "Design and maintain high-throughput streaming systems using Kafka and Redis."
    assert job_record["seniority"] == "senior"
    assert job_record["skills"] == ["Distributed Systems", "Python", "FastAPI"]

    # Verify extract_job_facts in conductor processes it into facts dictionary
    from backend.app.services.interview_v2.conductor import extract_job_facts
    facts = extract_job_facts(job_record)
    assert facts["job_title"] == "The job title is Senior Distributed Systems Engineer."
    assert facts["seniority"] == "The seniority level is senior."
    assert facts["required_skill_1"] == "Required technical skill: Distributed Systems."
    assert facts["required_skill_2"] == "Required technical skill: Python."
    assert facts["required_skill_3"] == "Required technical skill: FastAPI."
    assert "Kafka" in facts["description_fact_001"]


@pytest.mark.asyncio
async def test_p0_2_runner_end_and_rest_fallback_evaluate_exactly_once():
    """Verify that runner completion schedules evaluation exactly once, and repeated finalize calls are idempotent."""
    async with AsyncSessionLocal() as db:
        now_ts = datetime.now(timezone.utc).timestamp()
        recruiter = User(
            email=f"recruiter_p02_{now_ts}@example.com",
            full_name="Recruiter P02",
            role="recruiter",
            password_hash="pw",
        )
        candidate = User(
            email=f"candidate_p02_{now_ts}@example.com",
            full_name="Candidate P02",
            role="candidate",
            password_hash="pw",
        )
        db.add_all([recruiter, candidate])
        await db.flush()

        job = JobPosting(
            job_title="Full Stack Engineer",
            department="Engineering",
            recruiter_id=recruiter.id,
            status="active",
        )
        db.add(job)
        await db.flush()

        app_record = JobApplication(
            job_id=job.id,
            candidate_id=candidate.id,
            full_name=candidate.full_name,
            email=candidate.email,
            status="interview_ready",
        )
        db.add(app_record)
        await db.flush()

        session = InterviewSession(
            application_id=app_record.id,
            job_id=job.id,
            status="in_progress",
            current_phase="deep_dive",
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    ws = FakeWebSocket()
    runner = SessionRunner(
        session_id=session_id,
        websocket=ws,
        flux_client=None,
        aura_client=FakeTTS(),
        script=make_sample_script(),
    )

    with patch("backend.app.services.interview_v2.finalizer.run_evaluation_for_session") as mock_eval_task:
        await runner.start()
        await asyncio.sleep(0.05)

        # 1. Runner finishes via end button -> closing speech starts
        await runner.on_end_button(request_id="req-p02-1")
        await asyncio.sleep(0.05)
        # Client finishes playback
        await runner.on_playback_ended(runner.state.active_speech_id)
        await asyncio.sleep(0.10)

        # Verify SessionEnded emitted
        end_events = [m for m in ws.sent_messages if m.get("type") == "SessionEnded"]
        assert len(end_events) == 1
        assert end_events[0]["status"] == "completed"

        # Evaluation scheduled exactly once by runner
        assert mock_eval_task.call_count == 1

        async with AsyncSessionLocal() as db:
            s_row = (await db.execute(select(InterviewSession).where(InterviewSession.id == session_id))).scalar_one()
            assert s_row.status == "completed"
            app_row = (await db.execute(select(JobApplication).where(JobApplication.id == app_record.id))).scalar_one()
            assert app_row.status == "interview_completed"

            # Verify evaluation row was created in DB
            eval_rows = (await db.execute(select(InterviewEvaluation).where(InterviewEvaluation.session_id == session_id))).scalars().all()
            assert len(eval_rows) == 1

        # 2. REST end fallback arrives after WS completion
        res_rest = await finalize_interview_session(session_id, ended_by="candidate")
        assert res_rest["already_completed"] is True
        assert res_rest["evaluation_scheduled"] is False

        # Evaluation still only scheduled once!
        assert mock_eval_task.call_count == 1

        # 3. Duplicate finalize call
        res_dup = await finalize_interview_session(session_id, ended_by="candidate")
        assert res_dup["already_completed"] is True
        assert res_dup["evaluation_scheduled"] is False
        assert mock_eval_task.call_count == 1

        async with AsyncSessionLocal() as db:
            eval_rows_final = (await db.execute(select(InterviewEvaluation).where(InterviewEvaluation.session_id == session_id))).scalars().all()
            assert len(eval_rows_final) == 1

        await runner.stop()


@pytest.mark.asyncio
async def test_p0_3_commit_exception_sends_session_error_and_does_not_send_session_ended():
    """Verify that when database commit fails, runner sends SessionError(SessionPersistenceFailed) and never sends SessionEnded."""
    ws = FakeWebSocket()
    runner = SessionRunner(
        session_id="test-fail-commit-session",
        websocket=ws,
        flux_client=None,
        aura_client=FakeTTS(),
        script=make_sample_script(),
    )

    with patch("backend.app.services.interview_v2.runner.AsyncSessionLocal") as mock_db_cls:
        mock_db = AsyncMock()
        mock_db_cls.return_value.__aenter__.return_value = mock_db
        # Simulate DB commit failure (e.g. database disk full / constraint / connection drop)
        mock_session_row = MagicMock(status="in_progress", is_practice=False, application_id="app-1", completed_at=None)
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_session_row
        mock_db.commit.side_effect = RuntimeError("Database transaction aborted unexpectedly")

        await runner.start()
        await asyncio.sleep(0.05)

        # Trigger completion via end button -> enters closing speech
        await runner.on_end_button(request_id="req-fail-commit-1")
        await asyncio.sleep(0.05)
        # Client finishes playback -> triggers finalizer which fails commit
        await runner.on_playback_ended(runner.state.active_speech_id)
        await asyncio.sleep(0.10)

        # Assert no SessionEnded was sent!
        end_events = [m for m in ws.sent_messages if m.get("type") == "SessionEnded"]
        assert len(end_events) == 0

        # Assert SessionError with SessionPersistenceFailed and retryable=True was sent
        error_events = [m for m in ws.sent_messages if m.get("type") == "SessionError"]
        assert len(error_events) == 1
        assert error_events[0]["error"] == "SessionPersistenceFailed"
        assert error_events[0]["retryable"] is True

        await runner.stop()


@pytest.mark.asyncio
async def test_rest_end_interview_endpoint_authorization_and_idempotency():
    """Verify REST end-interview enforces authorization, idempotency, and runner cleanup."""
    async with AsyncSessionLocal() as db:
        now_ts = datetime.now(timezone.utc).timestamp()
        candidate = User(
            email=f"candidate_{now_ts}@example.com",
            full_name="Candidate Tester",
            role="candidate",
            password_hash="pw",
        )
        recruiter = User(
            email=f"recruiter_{now_ts}@example.com",
            full_name="Recruiter Tester",
            role="recruiter",
            password_hash="pw",
        )
        unrelated_user = User(
            email=f"other_{now_ts}@example.com",
            full_name="Other User",
            role="candidate",
            password_hash="pw",
        )
        db.add_all([candidate, recruiter, unrelated_user])
        await db.flush()

        job = JobPosting(
            job_title="Software Engineer",
            department="Engineering",
            recruiter_id=recruiter.id,
            status="active",
        )
        db.add(job)
        await db.flush()

        app_record = JobApplication(
            job_id=job.id,
            candidate_id=candidate.id,
            full_name=candidate.full_name,
            email=candidate.email,
            status="interview_ready",
        )
        db.add(app_record)
        await db.flush()

        session = InterviewSession(
            application_id=app_record.id,
            job_id=job.id,
            status="in_progress",
            current_phase="deep_dive",
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    token_candidate = create_access_token({"sub": candidate.id, "email": candidate.email, "role": "candidate", "id": candidate.id})
    token_recruiter = create_access_token({"sub": recruiter.id, "email": recruiter.email, "role": "recruiter", "id": recruiter.id})
    token_unrelated = create_access_token({"sub": unrelated_user.id, "email": unrelated_user.email, "role": "candidate", "id": unrelated_user.id})

    with patch("backend.app.main._run_evaluation_for_session"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # 1. Unauthenticated request -> 401
            res_unauth = await client.post(f"/api/interview-sessions/{session_id}/end")
            assert res_unauth.status_code == 401

            # 2. Unauthorized user request -> 403
            res_forbidden = await client.post(
                f"/api/interview-sessions/{session_id}/end",
                headers={"Authorization": f"Bearer {token_unrelated}"},
            )
            assert res_forbidden.status_code == 403

            # Setup mock active runner in ACTIVE_RUNNERS
            mock_runner = MagicMock()
            mock_runner.stop = AsyncMock()
            ACTIVE_RUNNERS[session_id] = mock_runner

            # 3. Authorized candidate end interview -> 200
            res_candidate = await client.post(
                f"/api/interview-sessions/{session_id}/end",
                headers={"Authorization": f"Bearer {token_candidate}"},
            )
            assert res_candidate.status_code == 200
            data = res_candidate.json()
            assert data["status"] == "completed"
            assert data["session_id"] == session_id

            # Verify runner was popped and stopped
            assert session_id not in ACTIVE_RUNNERS
            mock_runner.stop.assert_awaited_once()

            # 4. Idempotent second call -> 200
            res_idempotent = await client.post(
                f"/api/interview-sessions/{session_id}/end",
                headers={"Authorization": f"Bearer {token_candidate}"},
            )
            assert res_idempotent.status_code == 200
            assert res_idempotent.json()["message"] == "Interview session already completed."


# =============================================================================
# 3. Recruiter Blueprint Security & Approval Consistency Tests
# =============================================================================

@pytest.mark.asyncio
async def test_blueprint_endpoint_redaction_and_token_validation():
    """Verify get_job_blueprint enforces strict auth and redacts candidate views."""
    async with AsyncSessionLocal() as db:
        now_ts = datetime.now(timezone.utc).timestamp()
        recruiter = User(
            email=f"recruiter_bp_{now_ts}@example.com",
            full_name="Recruiter BP",
            role="recruiter",
            password_hash="pw",
        )
        candidate = User(
            email=f"candidate_bp_{now_ts}@example.com",
            full_name="Candidate BP",
            role="candidate",
            password_hash="pw",
        )
        db.add_all([recruiter, candidate])
        await db.flush()

        job = JobPosting(
            job_title="Data Engineer",
            department="Data",
            recruiter_id=recruiter.id,
            status="active",
        )
        db.add(job)
        await db.flush()

        # Add blueprint with expectations and questions
        bp = InterviewBlueprint(
            job_id=job.id,
            version=1,
            status="approved",
            total_duration_mins=20,
            active_skill_mins=16.0,
            fixed_overhead_mins=4.0,
        )
        db.add(bp)
        await db.flush()

        sec = BlueprintSection(
            blueprint_id=bp.id,
            order_index=0,
            section_type="skill",
            title="SQL Deep Dive",
            allocated_minutes=5.0,
            target_rubric_tier="L3-L4",
        )
        db.add(sec)
        await db.flush()

        exp = BlueprintExpectation(
            section_id=sec.id,
            order_index=0,
            expectation_text="Understands complex joins and query plans",
            source_rubric_level="L4",
            importance="core",
        )
        probe_q = BlueprintQuestion(
            section_id=sec.id,
            order_index=0,
            question_role="probe",
            question_text="How would you optimize this query?",
            trigger_condition="If candidate misses index",
            source="llm",
        )
        db.add_all([exp, probe_q])

        job.active_blueprint_id = bp.id
        await db.commit()
        job_id = job.id

    token_recruiter = create_access_token({"sub": recruiter.id, "email": recruiter.email, "role": "recruiter", "id": recruiter.id})
    token_candidate = create_access_token({"sub": candidate.id, "email": candidate.email, "role": "candidate", "id": candidate.id})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Invalid Bearer token must return 401 Unauthorized (never silently fall back to public view)
        res_invalid_tok = await client.get(f"/api/jobs/{job_id}/blueprint", headers={"Authorization": "Bearer invalid.jwt.token"})
        assert res_invalid_tok.status_code == 401

        # 2. Authenticated Recruiter gets full rubric and probes
        res_recruiter = await client.get(f"/api/jobs/{job_id}/blueprint", headers={"Authorization": f"Bearer {token_recruiter}"})
        assert res_recruiter.status_code == 200
        rec_data = res_recruiter.json()
        assert rec_data["sections"][0]["target_rubric_tier"] == "L3-L4"
        assert len(rec_data["sections"][0]["expectations"]) == 1
        assert rec_data["sections"][0]["expectations"][0]["expectation_text"] == "Understands complex joins and query plans"
        assert any(q["question_role"] == "probe" for q in rec_data["sections"][0]["questions"])

        # 3. Candidate receives redacted view (no internal expectations, no target rubric tier, no probes)
        res_candidate = await client.get(f"/api/jobs/{job_id}/blueprint", headers={"Authorization": f"Bearer {token_candidate}"})
        assert res_candidate.status_code == 200
        cand_data = res_candidate.json()
        assert cand_data["sections"][0]["target_rubric_tier"] is None
        assert cand_data["sections"][0]["expectations"] == []
        assert not any(q["question_role"] == "probe" for q in cand_data["sections"][0]["questions"])


@pytest.mark.asyncio
async def test_blueprint_approval_and_application_gate_with_errors():
    """Verify that approval is blocked when validation errors exist, and application is gated."""
    async with AsyncSessionLocal() as db:
        now_ts = datetime.now(timezone.utc).timestamp()
        recruiter = User(
            email=f"recruiter_gate_{now_ts}@example.com",
            full_name="Recruiter Gate",
            role="recruiter",
            password_hash="pw",
        )
        candidate = User(
            email=f"candidate_gate_{now_ts}@example.com",
            full_name="Candidate Gate",
            role="candidate",
            password_hash="pw",
        )
        db.add_all([recruiter, candidate])
        await db.flush()

        job = JobPosting(
            job_title="Data Engineer (Junior)",
            department="Data",
            seniority_level="entry",
            recruiter_id=recruiter.id,
            status="active",
        )
        db.add(job)
        await db.flush()

        skill = JobSkill(job_id=job.id, name="Distributed Systems", priority_tier="P0", weight_percentage=100)
        db.add(skill)
        await db.flush()

        # Blueprint with blocking error: missing P0 skill section
        bp = InterviewBlueprint(
            job_id=job.id,
            version=1,
            status="draft",
            total_duration_mins=20,
            active_skill_mins=16.0,
            fixed_overhead_mins=4.0,
            validation_report={"errors": ["Missing section for P0 skill 'Distributed Systems'"], "warnings": []},
        )
        db.add(bp)
        await db.flush()

        sec = BlueprintSection(
            blueprint_id=bp.id,
            order_index=0,
            section_type="welcome",
            title="Welcome",
            allocated_minutes=20.0,
        )
        db.add(sec)
        await db.commit()
        job_id = job.id
        bp_id = bp.id

    token_candidate = create_access_token({"sub": candidate.id, "email": candidate.email, "role": "candidate", "id": candidate.id})

    # 1. Attempting to approve blueprint with validation errors must raise ValueError
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError, match="Approval blocked due to validation errors"):
            await approve_job_blueprint(db, job_id, bp_id, user_id=recruiter.id)

    # 2. Check candidate application gate: apply_to_job must reject with 400
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res_apply = await client.post(
            f"/api/candidate/apply/{job_id}",
            json={"notes": "Applying"},
            headers={"Authorization": f"Bearer {token_candidate}"},
        )
        assert res_apply.status_code == 400
        assert "not accepting applications" in res_apply.json()["detail"]
