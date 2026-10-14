"""Integration check for the mocked question-generation lifecycle.

Set GEMINI_MOCK=0 to exercise the real Gemini adapter with GEMINI_API_KEY.
The default mock keeps this test deterministic and free of provider charges.
"""

import asyncio
import os
import uuid
from pathlib import Path

os.environ.setdefault("GEMINI_MOCK", "1")

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.main import app
from backend.app import models


async def main() -> None:
    resume_path = Path(__file__).with_name("test_scanned.pdf")
    resume_bytes = resume_path.read_bytes()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            suffix = uuid.uuid4().hex
            recruiter_response = (
                await client.post(
                    "/api/auth/signup",
                    json={
                        "email": f"generation-recruiter-{suffix}@example.test",
                        "password": "Password123!",
                        "full_name": "Generation Recruiter",
                        "role": "recruiter",
                        "company_name": "Generation Test Co",
                    },
                )
            )
            assert recruiter_response.status_code == 201, recruiter_response.text
            recruiter = recruiter_response.json()
            candidate_response = (
                await client.post(
                    "/api/auth/signup",
                    json={
                        "email": f"generation-candidate-{suffix}@example.test",
                        "password": "Password123!",
                        "full_name": "Generation Candidate",
                        "role": "candidate",
                    },
                )
            )
            assert candidate_response.status_code == 201, candidate_response.text
            candidate = candidate_response.json()
            recruiter_headers = {"Authorization": f"Bearer {recruiter['access_token']}"}
            candidate_headers = {"Authorization": f"Bearer {candidate['access_token']}"}
            job = (
                await client.post(
                    "/api/jobs",
                    headers=recruiter_headers,
                    json={
                        "job_title": "Generation Test Engineer",
                        "department": "Engineering",
                        "job_description": "Build reliable Python services.",
                        "interview_duration_mins": 20,
                        "skills": [
                            {
                                "name": "Python",
                                "category": "Core Technical",
                                "priority_tier": "P0",
                                "weight_percentage": 100,
                                "rubric_l3": "Ships maintainable production services.",
                                "rubric_l4": "Designs resilient service boundaries.",
                            }
                        ],
                    },
                )
            ).json()
            application = (
                await client.post(
                    "/api/applications",
                    headers=candidate_headers,
                    json={
                        "job_id": job["id"],
                        "candidate_id": candidate["user"]["id"],
                        "full_name": "Generation Candidate",
                        "email": candidate["user"]["email"],
                        "self_reported_experience_years": 3,
                    },
                )
            ).json()
            app_id = application["id"]
            upload = await client.post(
                f"/api/applications/{app_id}/resume",
                headers=candidate_headers,
                files={"file": ("resume.pdf", resume_bytes, "application/pdf")},
            )
            assert upload.status_code == 200, upload.text
            submit = await client.patch(
                f"/api/applications/{app_id}/submit",
                headers=candidate_headers,
                json={},
            )
            assert submit.status_code == 200, submit.text

            async with AsyncSessionLocal() as db:
                run = (
                    await db.execute(
                        select(models.InterviewGenerationRun).where(
                            models.InterviewGenerationRun.application_id == app_id
                        )
                    )
                ).scalars().first()
                assert run and run.status == "succeeded", run.failure_reason if run else "missing run"
                questions = (
                    await db.execute(
                        select(models.InterviewQuestion).where(
                            models.InterviewQuestion.generation_run_id == run.id
                        )
                    )
                ).scalars().all()
                assert questions

                session = (
                    await db.execute(
                        select(models.InterviewSession).where(
                            models.InterviewSession.application_id == app_id
                        )
                    )
                ).scalars().first()

            candidate_session = await client.get(
                f"/api/interview-sessions/{session.id}", headers=candidate_headers
            )
            assert candidate_session.status_code == 200, candidate_session.text
            payload = candidate_session.json()
            assert all("expected_key_points" not in q for q in payload["questions"])
            assert "rubric" not in candidate_session.text.lower()
            print(f"PASS: generation run {run.id} produced {len(questions)} candidate-safe questions")


if __name__ == "__main__":
    asyncio.run(main())
