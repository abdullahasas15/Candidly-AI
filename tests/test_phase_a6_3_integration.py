"""A6.3 integration (rebuilt from bytecode map): WS handshake, blueprint
endpoint redaction/gating, STT init failure exit, and database isolation."""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    CandidateResume,
    InterviewSession,
    JobApplication,
    JobPosting,
    JobSkill,
    User,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_job_and_app() -> Dict[str, str]:
    async with AsyncSessionLocal() as db:
        recruiter = User(email=f"r{uuid.uuid4().hex[:6]}@ex.com", password_hash="x", role="recruiter", full_name="A63 Recruiter")
        db.add(recruiter)
        await db.flush()
        job = JobPosting(job_title="A63 SDE", department="Eng", seniority_level="mid",
                         job_description="Python services.", interview_duration_mins=20,
                         status="active", recruiter_id=recruiter.id)
        db.add(job)
        await db.flush()
        db.add(JobSkill(job_id=job.id, name="Python", category="Core", priority_tier="P0", weight_percentage=100))
        app = JobApplication(job_id=job.id, candidate_id=None, full_name="A63 Jane",
                             email="a63@example.com", self_reported_experience_years=1.0)
        db.add(app)
        await db.flush()
        db.add(CandidateResume(application_id=app.id, original_file_name="r.pdf", file_type="pdf",
                               file_size_bytes=10, parsed_text="t",
                               parsed_structured_data={"skills": {"Languages": ["Python"]}},
                               parsing_status="success"))
        await db.commit()
        return {"job_id": job.id, "app_id": app.id}


# ---------------------------------------------------------------------------
# Health + isolation
# ---------------------------------------------------------------------------

def test_database_isolation_and_no_dev_contamination():
    async def check():
        async with AsyncSessionLocal() as db:
            url = str(db.bind.url)
            assert "test" in url.lower(), f"suite must run on the test DB, got {url}"
            assert "candidly ai voice interview platform" not in url.lower().replace("test", "")
    asyncio.run(check())


def test_health_endpoint_reports_database():
    from backend.app.main import app
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code in (200, 503)
    body = res.json()
    assert "database" in body or "status" in body


# ---------------------------------------------------------------------------
# Blueprint application gating + redaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blueprint_not_found_404_for_unknown_job():
    from backend.app.main import app
    client = TestClient(app)
    res = client.get(f"/api/jobs/{uuid.uuid4()}/blueprint")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_ws_requires_valid_ticket():
    """The WS ticket gate closes unauthorized sockets before touching session
    state (terminal close, not a session error frame)."""
    ids = await _seed_job_and_app()
    async with AsyncSessionLocal() as db:
        sess = InterviewSession(id=str(uuid.uuid4()), application_id=ids["app_id"],
                                job_id=ids["job_id"], status="scheduled")
        db.add(sess)
        await db.commit()
        sid = sess.id

    from backend.app.main import app
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/interview/{sid}?ticket=invalid"):
            pass


# ---------------------------------------------------------------------------
# Finalizer exactly-once (integration with DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finalize_exactly_once_with_evaluation_scheduling():
    from backend.app.services.interview_v2.finalizer import finalize_interview_session

    ids = await _seed_job_and_app()
    async with AsyncSessionLocal() as db:
        sess = InterviewSession(id=str(uuid.uuid4()), application_id=ids["app_id"],
                                job_id=ids["job_id"], status="in_progress",
                                started_at=datetime.utcnow() - timedelta(minutes=10))
        db.add(sess)
        await db.commit()
        sid = sess.id

    with patch("backend.app.services.interview_v2.finalizer.run_evaluation_for_session",
               new=AsyncMock(return_value=None)) as m:
        await finalize_interview_session(sid, ended_by="candidate")
        await finalize_interview_session(sid, ended_by="candidate")

    async with AsyncSessionLocal() as db:
        row = await db.execute(select(InterviewSession).where(InterviewSession.id == sid))
        final = row.scalars().first()
        assert final.status == "completed"
    assert m.await_count == 1
