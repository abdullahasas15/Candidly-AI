"""Zero-touch blueprint auto-approval in background generation.

A freshly generated blueprint with no validation errors must go live
automatically (warnings auto-confirmed) so recruiters never face a manual
approval step. Validation errors must leave the draft untouched for review.
"""

import pytest

from backend.app import main as app_main


class FakeBlueprint:
    def __init__(self, errors=None):
        self.id = "bp-1"
        self.validation_report = {"errors": errors or [], "warnings": ["quality note"]}


class FakeResult:
    def scalars(self):
        return self

    def first(self):
        return None


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt):
        return FakeResult()


@pytest.mark.asyncio
async def test_background_generation_auto_approves_when_no_errors(monkeypatch):
    approved = {}

    async def fake_generate(**kwargs):
        return {"sections": [], "generation_stages_ms": {}}

    async def fake_save(db, blueprint_data, auto_approve=False):
        return FakeBlueprint(errors=[])

    async def fake_approve(db, job_id, blueprint_id, user_id, confirmed_warnings=False):
        approved.update(
            job_id=job_id,
            blueprint_id=blueprint_id,
            user_id=user_id,
            confirmed=confirmed_warnings,
        )
        return FakeBlueprint(errors=[])

    monkeypatch.setattr(app_main, "generate_job_blueprint", fake_generate)
    monkeypatch.setattr(app_main, "save_job_blueprint", fake_save)
    monkeypatch.setattr(app_main, "approve_job_blueprint", fake_approve)
    monkeypatch.setattr(
        app_main, "serialize_blueprint", lambda bp, current_job=None: {"id": bp.id, "status": "approved"}
    )
    monkeypatch.setattr(app_main, "AsyncSessionLocal", lambda: FakeSession())

    task = app_main.BlueprintGenerationTask("job-1")
    await app_main._run_blueprint_generation_background(
        job_id="job-1",
        job_title="AI Engineer",
        seniority_level="mid",
        duration_mins=30,
        skills_data=[],
        job_description="JD",
        task=task,
        recruiter_id="recruiter-1",
    )

    assert task.status == "completed"
    assert approved == {
        "job_id": "job-1",
        "blueprint_id": "bp-1",
        "user_id": "recruiter-1",
        "confirmed": True,
    }
    assert task.blueprint["status"] == "approved"


@pytest.mark.asyncio
async def test_background_generation_leaves_draft_when_errors(monkeypatch):
    approved = {}

    async def fake_generate(**kwargs):
        return {"sections": [], "generation_stages_ms": {}}

    async def fake_save(db, blueprint_data, auto_approve=False):
        return FakeBlueprint(errors=["Question missing a question mark"])

    async def fake_approve(db, job_id, blueprint_id, user_id, confirmed_warnings=False):
        approved.update(called=True)
        return FakeBlueprint(errors=[])

    monkeypatch.setattr(app_main, "generate_job_blueprint", fake_generate)
    monkeypatch.setattr(app_main, "save_job_blueprint", fake_save)
    monkeypatch.setattr(app_main, "approve_job_blueprint", fake_approve)
    monkeypatch.setattr(
        app_main, "serialize_blueprint", lambda bp, current_job=None: {"id": bp.id, "status": "draft"}
    )
    monkeypatch.setattr(app_main, "AsyncSessionLocal", lambda: FakeSession())

    task = app_main.BlueprintGenerationTask("job-2")
    await app_main._run_blueprint_generation_background(
        job_id="job-2",
        job_title="Data Engineer",
        seniority_level="senior",
        duration_mins=30,
        skills_data=[],
        job_description="JD",
        task=task,
        recruiter_id="recruiter-2",
    )

    assert task.status == "completed"
    assert approved == {}  # never auto-approved with validation errors
    assert task.blueprint["status"] == "draft"


@pytest.mark.asyncio
async def test_background_generation_survives_autoapprove_failure(monkeypatch):
    async def fake_generate(**kwargs):
        return {"sections": [], "generation_stages_ms": {}}

    async def fake_save(db, blueprint_data, auto_approve=False):
        return FakeBlueprint(errors=[])

    async def fake_approve(db, job_id, blueprint_id, user_id, confirmed_warnings=False):
        raise ValueError("approval exploded")

    monkeypatch.setattr(app_main, "generate_job_blueprint", fake_generate)
    monkeypatch.setattr(app_main, "save_job_blueprint", fake_save)
    monkeypatch.setattr(app_main, "approve_job_blueprint", fake_approve)
    monkeypatch.setattr(
        app_main, "serialize_blueprint", lambda bp, current_job=None: {"id": bp.id, "status": "draft"}
    )
    monkeypatch.setattr(app_main, "AsyncSessionLocal", lambda: FakeSession())

    task = app_main.BlueprintGenerationTask("job-3")
    await app_main._run_blueprint_generation_background(
        job_id="job-3",
        job_title="DevOps",
        seniority_level="mid",
        duration_mins=30,
        skills_data=[],
        job_description="JD",
        task=task,
        recruiter_id="recruiter-3",
    )

    # Generation itself completed; approval stays available in the UI
    assert task.status == "completed"
    assert task.blueprint["status"] == "draft"
