import asyncio
import os
import base64
import hmac
import time
from dotenv import load_dotenv
from datetime import datetime
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from fastapi import BackgroundTasks, FastAPI, Depends, HTTPException, status, File, UploadFile, Form, Body, Response, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, text, update, or_
from sqlalchemy.orm import selectinload

from backend.app.database import engine, Base, get_db, AsyncSessionLocal
from backend.app.models import (
    JobPosting, JobSkill, JobCertification, JobCustomQuestion, JobQuestionPlan, RoleTemplate,
    User, CandidateApplication, JobApplication, CandidateResume, ResumeDiscrepancyFlag, CandidateIdVerification,
    InterviewSession, InterviewQuestion, InterviewGenerationRun, InterviewTranscriptTurn, AuditEvent,
    InterviewEvaluation, InterviewSkillScore, InterviewIntegrityEvent, InterviewFeedback,
    InterviewBlueprint, BlueprintSection, BlueprintExpectation, BlueprintQuestion,
    CandidatePersonalization, SessionExpectationCoverage,
)
from backend.app.schemas import (
    JobCreate, JobResponse, RoleTemplateResponse, UserCreate, UserLogin, UserResponse, CandidateApplicationResponse,
    JobApplicationCreate, JobApplicationUpdate, JobApplicationResponse, JobApplicationListItem,
    CandidateResumeResponse, ResumeDiscrepancyFlagResponse, CandidateIdVerificationResponse,
    TokenResponse, InterviewSessionCreate, InterviewSessionResponse,
    InterviewQuestionCreate, InterviewQuestionResponse, CandidateApplicationPublicResponse,
    CandidateInterviewSessionResponse, InterviewTranscriptTurnResponse, AuditEventResponse,
    InterviewEvaluationResponse, InterviewSkillScoreResponse, CandidateSafeEvaluationSummary,
    InterviewIntegrityEventCreate, InterviewIntegrityEventResponse,
    InterviewFeedbackCreate, InterviewFeedbackResponse,
    RecruiterDecisionRequest, InterviewQuestionUpdateRequest, InterviewPlanApprovalRequest,
    InterviewSessionSettingsUpdate,
)
from backend.app.budgeting import calculate_question_budget
from backend.app.services.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_optional_current_user, require_role
)
from backend.app.services.resume_parser import (
    extract_text_from_file, parse_structured_resume_data, detect_discrepancies
)
from backend.app.services.question_generation.provider import check_ai_provider_health
from backend.app.services.question_generation.persistence import generate_for_application
from backend.app.services.interview.state_machine import SessionState, transition_session, InterviewPhase
from backend.app.services.interview.live_session import interview_manager, InterviewerBusyError
from backend.app.services.interview.turn_evaluator import evaluate_interview_session
from backend.app.services.interview.voice_pipeline import warmup_voice_models
from backend.app.services.blueprint import (
    generate_job_blueprint,
    generate_single_skill_section,
    save_job_blueprint,
    get_job_blueprint,
    approve_job_blueprint,
    ensure_job_blueprint,
    serialize_blueprint,
    BlueprintGenerationError,
    get_session_expectation_coverage,
    compute_job_input_hash,
    update_or_fork_job_blueprint,
    regenerate_blueprint_section,
    suggest_skills_from_jd,
)
from backend.app.services.blueprint.persistence import list_job_blueprint_versions
from backend.app.services.blueprint.contracts import (
    BlueprintApprovalRequest,
    SuggestSkillsRequest,
    BlueprintUpdatePayload,
)
import logging

logger = logging.getLogger(__name__)

# Background Blueprint Generation Tasks and Locks
class BlueprintGenerationTask:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = "in_progress"  # "in_progress", "completed", "failed"
        self.progress = 0.05
        self.current_stage = "budgeting"
        self.section_progress: Dict[str, Dict[str, Any]] = {}
        self.stage_timings: Dict[str, float] = {}
        self.blueprint: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.errors: List[str] = []
        self.can_retry: bool = True
        self.created_at = time.time()
        self.updated_at = time.time()


_ACTIVE_BLUEPRINT_TASKS: Dict[str, BlueprintGenerationTask] = {}
_BLUEPRINT_GENERATION_LOCKS: dict[str, asyncio.Lock] = {}


async def _run_blueprint_generation_background(
    job_id: str,
    job_title: str,
    seniority_level: str,
    duration_mins: int,
    skills_data: List[Dict[str, Any]],
    job_description: str,
    task: BlueprintGenerationTask,
):
    """Background worker for job blueprint generation with live progress reporting."""
    try:
        def on_progress(stage: str, progress: float, section_data: Optional[Dict[str, Any]] = None):
            task.current_stage = stage
            task.progress = progress
            task.updated_at = time.time()
            if section_data and "skill_name" in section_data:
                task.section_progress[section_data["skill_name"]] = section_data

        blueprint_data = await generate_job_blueprint(
            job_id=job_id,
            job_title=job_title,
            seniority_level=seniority_level,
            duration_mins=duration_mins,
            skills=skills_data,
            job_description=job_description,
            progress_callback=on_progress,
        )

        task.current_stage = "saving"
        task.progress = 0.95
        task.stage_timings = blueprint_data.get("generation_stages_ms", {})

        async with AsyncSessionLocal() as session:
            j_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
            j_res = await session.execute(j_stmt)
            curr_job = j_res.scalars().first()

            blueprint = await save_job_blueprint(
                db=session,
                blueprint_data=blueprint_data,
                auto_approve=False,
            )
            task.blueprint = serialize_blueprint(blueprint, current_job=curr_job)
            task.status = "completed"
            task.progress = 1.0
            task.current_stage = "completed"
            task.updated_at = time.time()
            logger.info("Successfully completed background blueprint generation for job %s", job_id)
    except BlueprintGenerationError as exc:
        logger.error("Background blueprint generation failed for job %s: %s", job_id, exc)
        task.status = "failed"
        task.error = str(exc)
        task.errors = exc.errors
        task.can_retry = True
        task.updated_at = time.time()
    except Exception as exc:
        logger.exception("Unexpected error in background blueprint generation for job %s", job_id)
        task.status = "failed"
        task.error = f"Blueprint generation failed: {exc}"
        task.errors = [str(exc)]
        task.can_retry = True
        task.updated_at = time.time()


load_dotenv(
    "/Users/mohammadabdullah/Documents/CANDIDLY AI VOICE INTERVIEW PLATFORM/.env",
    override=True,
)


async def record_audit(
    db: AsyncSession,
    actor: Optional[User],
    event_type: str,
    *,
    status_value: str = "success",
    job_id: Optional[str] = None,
    application_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    db.add(AuditEvent(
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        event_type=event_type,
        status=status_value,
        job_id=job_id,
        application_id=application_id,
        session_id=session_id,
        metadata_json=metadata,
    ))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables & schema migrations
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            migrations = [
                "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS salary_range_min FLOAT;",
                "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS salary_range_max FLOAT;",
                "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS salary_currency VARCHAR(10) DEFAULT 'USD';",
                "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS recruiter_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500);",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(50) DEFAULT 'local';",
                "ALTER TABLE candidate_resumes ADD COLUMN IF NOT EXISTS file_data BYTEA;",
                "ALTER TABLE candidate_resumes ADD COLUMN IF NOT EXISTS file_base64 TEXT;",
                "ALTER TABLE candidate_resumes ALTER COLUMN original_file_path DROP NOT NULL;",
                "ALTER TABLE candidate_id_verification ALTER COLUMN live_photo_path TYPE TEXT;",
                "ALTER TABLE candidate_id_verification ALTER COLUMN government_id_path TYPE TEXT;",
                "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS current_question_index INTEGER DEFAULT 0;",
                "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;",
                "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;",
                "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS system_prompt_snapshot TEXT;",
                "ALTER TABLE interview_questions ADD COLUMN IF NOT EXISTS generation_run_id VARCHAR(36) REFERENCES interview_generation_runs(id) ON DELETE SET NULL;",
                "ALTER TABLE interview_questions ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMP;",
            ]
            for mig in migrations:
                try:
                    await conn.execute(text(mig))
                except Exception:
                    pass
    except (ConnectionRefusedError, OSError) as e:
        logger.error(
            "\n" + "=" * 70 + "\n"
            "CRITICAL: Failed to connect to PostgreSQL database!\n"
            "Error: Connection refused on localhost:5432.\n"
            "To start PostgreSQL on demand, run in your terminal:\n"
            "  ./scripts/db.sh start\n"
            "=" * 70 + "\n"
        )
        raise

    # Check Gemini AI provider connectivity
    try:
        ai_health = await asyncio.to_thread(check_ai_provider_health)
        if ai_health.get("status") == "ok":
            logger.info("✓ Gemini AI provider online (%sms, key: %s)", ai_health.get("latency_ms"), ai_health.get("key_source"))
        else:
            logger.error(
                "\n" + "=" * 75 + "\n"
                "CRITICAL: GEMINI AI PROVIDER UNREACHABLE OR API KEY INVALID!\n"
                f"Error: {ai_health.get('error')}\n"
                "Check GEMINI_API_KEY in your .env file or run scripts/check_gemini.py.\n"
                "=" * 75 + "\n"
            )
    except Exception as exc:
        logger.error("Failed to check Gemini AI provider health: %s", exc)

    # Verify backup provider (OpenRouter/NVIDIA) structured output support
    try:
        from backend.app.services.llm_router import verify_backup_structured_output
        bk_check = await asyncio.to_thread(verify_backup_structured_output)
        if bk_check.get("supported"):
            logger.info("✓ Backup provider (OpenRouter/NVIDIA) structured output verified on %s", bk_check.get("model"))
        else:
            logger.warning("⚠ Backup provider structured output check: %s", bk_check.get("error") or bk_check.get("reason"))
    except Exception as exc:
        logger.warning("Failed to verify backup provider structured output: %s", exc)

    # Seed & verify Role Templates
    try:
        from backend.app.services.role_templates import load_role_templates
        async with AsyncSessionLocal() as session:
            await load_role_templates(session)
        logger.info("✓ Role templates loaded and verified.")
    except Exception as exc:
        logger.error("Failed to load role templates: %s", exc)

    # Warm up local voice models (Parakeet, Kokoro, Silero VAD, Smart Turn v3, Gemini client) in background
    if os.getenv("SKIP_VOICE_WARMUP", "").lower() not in {"1", "true", "yes"}:
        asyncio.create_task(warmup_voice_models())

    yield
    await engine.dispose()


async def _generate_application_questions(application_id: str) -> None:
    """[DEPRECATED] Legacy question generation off-request; preserved for legacy sessions without blueprints."""
    try:
        async with AsyncSessionLocal() as session:
            await generate_for_application(application_id, session)
    except Exception:
        logger.exception("Interview question generation failed for application %s", application_id)


async def _run_candidate_personalization(application_id: str) -> None:
    """Run candidate personalization and materialize blueprint interview session off-request (R3.1/R3.2/R3.3)."""
    try:
        async with AsyncSessionLocal() as db:
            app_stmt = (
                select(JobApplication)
                .where(JobApplication.id == application_id)
                .options(
                    selectinload(JobApplication.job),
                    selectinload(JobApplication.resume),
                    selectinload(JobApplication.discrepancy_flags),
                )
            )
            application = (await db.execute(app_stmt)).scalars().first()
            if not application or not application.job:
                return

            job = application.job
            if job.active_blueprint_id:
                from backend.app.services.interview.personalization import generate_candidate_personalization
                from backend.app.services.interview.plan_materializer import materialize_blueprint_session_plan

                # 1. Non-blocking candidate personalization
                await generate_candidate_personalization(application.id, db)

                # 2. Find or create scheduled interview session
                sess_stmt = (
                    select(InterviewSession)
                    .where(
                        InterviewSession.application_id == application.id,
                        InterviewSession.status.in_(["scheduled", "preflight"]),
                    )
                    .order_by(InterviewSession.created_at.desc())
                )
                session = (await db.execute(sess_stmt)).scalars().first()
                if not session:
                    session = InterviewSession(
                        application_id=application.id,
                        job_id=job.id,
                        status="scheduled",
                        duration_planned_mins=job.interview_duration_mins or 20,
                        gemini_model_used=os.getenv("GEMINI_MODEL_LIVE", "gemini-3.5-flash-lite"),
                    )
                    db.add(session)
                    await db.flush()

                # 3. Materialize runtime question plan from blueprint
                await materialize_blueprint_session_plan(session, db)

                # 4. Record succeeded run so CandidateDashboard is_ready checks pass immediately
                run_stmt = (
                    select(InterviewGenerationRun)
                    .where(InterviewGenerationRun.application_id == application.id)
                    .order_by(InterviewGenerationRun.created_at.desc())
                )
                run = (await db.execute(run_stmt)).scalars().first()
                if not run:
                    run = InterviewGenerationRun(
                        application_id=application.id,
                        job_id=job.id,
                        status="succeeded",
                        model_name=os.getenv("GEMINI_MODEL_PLAN", "gemini-3.5-flash"),
                        prompt_template_version="r3_blueprint",
                        input_snapshot_hash="blueprint_" + str(job.active_blueprint_id),
                        completed_at=datetime.utcnow(),
                    )
                    db.add(run)
                else:
                    run.status = "succeeded"
                    run.completed_at = datetime.utcnow()

                await db.commit()
                logger.info("Personalization and blueprint plan materialized for app %s", application.id)
            else:
                # Fallback to legacy generator for jobs without blueprints
                await generate_for_application(application_id, db)
    except Exception:
        logger.exception("Candidate personalization/plan materialization failed for application %s", application_id)


async def _run_evaluation_for_session(session_id: str) -> None:
    """Run post-interview Judge evaluation off-request when a session completes."""
    try:
        async with AsyncSessionLocal() as session:
            await evaluate_interview_session(session_id, session)
    except Exception:
        logger.exception("Post-interview evaluation failed for session %s", session_id)


app = FastAPI(
    title="Candidly AI Platform API",
    description="Autonomous Voice Interview & Proctoring Platform API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _public_job_payload(job: JobPosting) -> dict:
    """Return only role information intended for candidate-facing clients."""
    return {
        "id": job.id,
        "job_title": job.job_title,
        "department": job.department,
        "job_description": job.job_description,
        "seniority_level": job.seniority_level,
        "employment_type": job.employment_type,
        "workplace_model": job.workplace_model,
        "permitted_locations": job.permitted_locations or [],
        "min_degree_level": job.min_degree_level,
        "degree_enforcement_type": job.degree_enforcement_type,
        "accepted_majors": job.accepted_majors or [],
        "min_cgpa": job.min_cgpa,
        "cgpa_strict_filter": job.cgpa_strict_filter,
        "grad_year_start": job.grad_year_start,
        "grad_year_end": job.grad_year_end,
        "total_experience_years": job.total_experience_years,
        "domain_experience_years": job.domain_experience_years,
        "leadership_required": job.leadership_required,
        "interview_duration_mins": job.interview_duration_mins,
        "salary_range_min": job.salary_range_min,
        "salary_range_max": job.salary_range_max,
        "salary_currency": job.salary_currency or "USD",
        "status": job.status,
        "created_at": job.created_at,
        "skills": [
            {
                "id": skill.id,
                "job_id": skill.job_id,
                "name": skill.name,
                "category": skill.category,
            }
            for skill in (job.skills or [])
        ],
        "custom_questions": [
            {
                "id": question.id,
                "job_id": question.job_id,
                "question_text": question.question_text,
                "category": question.category,
                "difficulty_level": question.difficulty_level,
                "question_type": question.question_type,
                "is_required": question.is_required,
                "options": question.options or [],
            }
            for question in (job.custom_questions or [])
        ],
        "active_blueprint_id": job.active_blueprint_id,
        "blueprint_status": getattr(job, "blueprint_status", None),
        "blueprint_is_stale": getattr(job, "blueprint_is_stale", False),
        "accepts_applications": getattr(job, "accepts_applications", False),
    }


async def _enrich_jobs_with_blueprint_status(jobs: List[JobPosting], db: AsyncSession):
    """Batch-enrich job instances with live blueprint status, staleness, and gate acceptance."""
    bp_ids = [j.active_blueprint_id for j in jobs if j.active_blueprint_id]
    bp_map = {}
    if bp_ids:
        bp_stmt = select(InterviewBlueprint).where(InterviewBlueprint.id.in_(bp_ids))
        res = await db.execute(bp_stmt)
        for bp in res.scalars().all():
            bp_map[bp.id] = bp

    for job in jobs:
        bp = bp_map.get(job.active_blueprint_id)
        if bp:
            curr_hash = compute_job_input_hash(job)
            is_stale = bp.is_stale or (bool(bp.input_hash) and bp.input_hash != curr_hash)
            job.blueprint_status = bp.status
            job.blueprint_is_stale = is_stale
            job.accepts_applications = (bp.status == "approved" and not is_stale)
        else:
            job.blueprint_status = None
            job.blueprint_is_stale = False
            job.accepts_applications = False


def _candidate_application_payload(application: JobApplication) -> dict:
    """Serialize an application without recruiter-only job or interview data."""
    return {
        "id": application.id,
        "job_id": application.job_id,
        "candidate_id": application.candidate_id,
        "full_name": application.full_name,
        "email": application.email,
        "phone": application.phone,
        "linkedin_url": application.linkedin_url,
        "portfolio_url": application.portfolio_url,
        "status": application.status,
        "applied_at": application.applied_at,
        "self_reported_experience_years": application.self_reported_experience_years,
        "fit_pitch": application.fit_pitch,
        "expected_salary": application.expected_salary,
        "expected_salary_currency": application.expected_salary_currency,
        "screening_answers": application.screening_answers or [],
        "work_authorization": application.work_authorization,
        "visa_sponsorship_needed": application.visa_sponsorship_needed,
        "created_at": application.created_at,
        "updated_at": application.updated_at,
        "job": _public_job_payload(application.job) if application.job else None,
        "resume": (
            {
                "id": application.resume.id,
                "application_id": application.resume.application_id,
                "original_file_name": application.resume.original_file_name,
                "file_type": application.resume.file_type,
                "file_size_bytes": application.resume.file_size_bytes,
                "parsed_text": application.resume.parsed_text,
                "parsed_structured_data": application.resume.parsed_structured_data or {},
                "ocr_used": application.resume.ocr_used,
                "parsing_status": application.resume.parsing_status,
                "created_at": application.resume.created_at,
            }
            if application.resume
            else None
        ),
    }

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Candidly AI Platform Backend",
        "database": "Connected"
    }

@app.get("/api/health/ai")
async def ai_health_check():
    from backend.app.services.llm_router import check_all_llm_health
    health = await asyncio.to_thread(check_all_llm_health)
    return health


@app.get("/api/role-templates", response_model=List[RoleTemplateResponse])
async def list_role_templates_endpoint(
    db: AsyncSession = Depends(get_db)
):
    from backend.app.services.role_templates import get_all_role_templates
    return await get_all_role_templates(db)


@app.get("/api/role-templates/{role_key}", response_model=RoleTemplateResponse)
async def get_role_template_endpoint(
    role_key: str,
    db: AsyncSession = Depends(get_db)
):
    from backend.app.services.role_templates import get_role_template_by_key
    tpl = await get_role_template_by_key(db, role_key)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"Role template '{role_key}' not found")
    return tpl


@app.get("/api/role-templates/{role_key}/skills")
async def get_role_template_skills_endpoint(
    role_key: str,
    seniority: str = "mid",
    db: AsyncSession = Depends(get_db)
):
    from backend.app.services.role_templates import get_role_template_by_key, extract_template_skills_for_seniority
    tpl = await get_role_template_by_key(db, role_key)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"Role template '{role_key}' not found")
    skills = extract_template_skills_for_seniority(tpl, seniority)
    return {
        "role_key": role_key,
        "role_template_id": tpl.id,
        "role_template_version": tpl.version,
        "display_name": tpl.display_name,
        "seniority": seniority,
        "skills": skills,
        "default_duration_mins": tpl.default_duration_mins,
        "default_pacing": tpl.default_pacing,
        "default_interviewer_tone": tpl.default_interviewer_tone,
        "suggested_certifications": tpl.suggested_certifications,
    }


@app.get("/api/jobs", response_model=List[JobResponse])
async def list_jobs(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    is_recruiter = current_user and current_user.role == "recruiter"
    stmt = (
        select(JobPosting)
        .options(
            selectinload(JobPosting.skills),
            selectinload(JobPosting.certifications),
            selectinload(JobPosting.custom_questions),
            selectinload(JobPosting.question_plans)
        )
        .order_by(JobPosting.created_at.desc())
    )
    if is_recruiter:
        stmt = stmt.where(JobPosting.recruiter_id == current_user.id)
    else:
        stmt = stmt.where(JobPosting.status == "active")
    result = await db.execute(stmt)
    jobs = list(result.scalars().all())
    await _enrich_jobs_with_blueprint_status(jobs, db)
    if is_recruiter:
        return jobs
    return [_public_job_payload(job) for job in jobs]

@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(JobPosting)
        .where(JobPosting.id == job_id)
        .options(
            selectinload(JobPosting.skills),
            selectinload(JobPosting.certifications),
            selectinload(JobPosting.custom_questions),
            selectinload(JobPosting.question_plans)
        )
    )
    result = await db.execute(stmt)
    job = result.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    await _enrich_jobs_with_blueprint_status([job], db)
    if current_user and current_user.role == "recruiter":
        if job.recruiter_id != current_user.id:
            raise HTTPException(status_code=404, detail="Job posting not found")
        return job
    if job.status != "active":
        raise HTTPException(status_code=404, detail="Job posting not found")
    return _public_job_payload(job)


@app.patch("/api/jobs/{job_id}", response_model=JobResponse)
async def update_job_endpoint(
    job_id: str,
    payload: Dict[str, Any],
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    """Update job fields, skills, duration, or policy, marking active blueprint stale if inputs change."""
    job_stmt = (
        select(JobPosting)
        .where(JobPosting.id == job_id)
        .options(
            selectinload(JobPosting.skills),
            selectinload(JobPosting.certifications),
            selectinload(JobPosting.custom_questions),
            selectinload(JobPosting.question_plans),
        )
    )
    res = await db.execute(job_stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    if job.recruiter_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have permission to modify this job.")

    # Update scalar fields
    for field in [
        "role_key", "role_template_id", "role_template_version",
        "job_title", "department", "job_description", "seniority_level",
        "employment_type", "workplace_model", "min_degree_level",
        "interview_duration_mins", "max_followup_depth", "pacing_strictness",
        "interviewer_tone", "salary_range_min", "salary_range_max",
    ]:
        if field in payload and payload[field] is not None:
            setattr(job, field, payload[field])

    # If skills are updated in payload:
    if "skills" in payload and isinstance(payload["skills"], list):
        existing_skills_map = {s.id: s for s in job.skills}
        for s_data in payload["skills"]:
            s_id = s_data.get("id")
            if s_id and s_id in existing_skills_map:
                sk = existing_skills_map[s_id]
                for k in [
                    "name", "category", "priority_tier", "weight_percentage",
                    "template_skill_key", "target_level_min", "target_level_max", "source",
                    "rubric_l1", "rubric_l2", "rubric_l3", "rubric_l4", "rubric_l5",
                ]:
                    if k in s_data:
                        setattr(sk, k, s_data[k])
            else:
                new_skill = JobSkill(
                    job_id=job.id,
                    name=s_data["name"],
                    category=s_data.get("category", "Core Technical"),
                    priority_tier=s_data.get("priority_tier", "P1"),
                    weight_percentage=float(s_data.get("weight_percentage", 25.0)),
                    template_skill_key=s_data.get("template_skill_key"),
                    target_level_min=s_data.get("target_level_min"),
                    target_level_max=s_data.get("target_level_max"),
                    source=s_data.get("source", "recruiter"),
                    rubric_l1=s_data.get("rubric_l1"),
                    rubric_l2=s_data.get("rubric_l2"),
                    rubric_l3=s_data.get("rubric_l3"),
                    rubric_l4=s_data.get("rubric_l4"),
                    rubric_l5=s_data.get("rubric_l5"),
                )
                db.add(new_skill)

    await db.flush()

    # Re-check staleness against active blueprint
    new_hash = compute_job_input_hash(job)
    if job.active_blueprint_id:
        bp_stmt = select(InterviewBlueprint).where(InterviewBlueprint.id == job.active_blueprint_id)
        bp_res = await db.execute(bp_stmt)
        active_bp = bp_res.scalars().first()
        if active_bp and active_bp.input_hash and active_bp.input_hash != new_hash:
            active_bp.is_stale = True

    await db.commit()
    await db.refresh(job)
    await _enrich_jobs_with_blueprint_status([job], db)
    return job

@app.post("/api/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    # 1. Create JobPosting instance
    recruiter_id = current_user.id if current_user else None
    job = JobPosting(
        role_key=payload.role_key or "custom",
        role_template_id=payload.role_template_id,
        role_template_version=payload.role_template_version,
        job_title=payload.job_title,
        recruiter_id=recruiter_id,
        department=payload.department,
        job_description=payload.job_description.strip() or "N/A",
        seniority_level=payload.seniority_level,
        employment_type=payload.employment_type,
        workplace_model=payload.workplace_model,
        permitted_locations=payload.permitted_locations,
        min_degree_level=payload.min_degree_level,
        degree_enforcement_type=payload.degree_enforcement_type,
        accepted_majors=payload.accepted_majors,
        min_cgpa=payload.min_cgpa,
        cgpa_strict_filter=payload.cgpa_strict_filter,
        grad_year_start=payload.grad_year_start,
        grad_year_end=payload.grad_year_end,
        total_experience_years=payload.total_experience_years,
        domain_experience_years=payload.domain_experience_years,
        leadership_required=payload.leadership_required,
        interview_duration_mins=payload.interview_duration_mins,
        allow_grace_extension=payload.allow_grace_extension,
        max_followup_depth=payload.max_followup_depth,
        pacing_strictness=payload.pacing_strictness,
        interviewer_tone=payload.interviewer_tone,
        integrity_policy_tier=payload.integrity_policy_tier,
        salary_range_min=payload.salary_range_min,
        salary_range_max=payload.salary_range_max,
        salary_currency=payload.salary_currency or "USD",
        status="active"
    )
    db.add(job)
    await db.flush()

    # 2. Add Skills
    for s in payload.skills:
        skill = JobSkill(
            job_id=job.id,
            name=s.name,
            category=s.category,
            priority_tier=s.priority_tier,
            weight_percentage=s.weight_percentage,
            template_skill_key=s.template_skill_key,
            target_level_min=s.target_level_min,
            target_level_max=s.target_level_max,
            source=s.source or "recruiter",
            rubric_l1=s.rubric_l1,
            rubric_l2=s.rubric_l2,
            rubric_l3=s.rubric_l3,
            rubric_l4=s.rubric_l4,
            rubric_l5=s.rubric_l5,
        )
        db.add(skill)

    # 3. Add Certifications
    for c in payload.certifications:
        cert = JobCertification(
            job_id=job.id,
            name=c.name,
            issuing_org=c.issuing_org,
            priority_tier=c.priority_tier,
            verification_required=c.verification_required
        )
        db.add(cert)

    # 4. Add Custom Screening Questions
    for q in payload.custom_questions:
        c_question = JobCustomQuestion(
            job_id=job.id,
            question_text=q.question_text,
            category=q.category,
            difficulty_level=q.difficulty_level,
            expected_key_points=q.expected_key_points,
            priority_tier=q.priority_tier,
            question_type=getattr(q, "question_type", "text"),
            is_required=getattr(q, "is_required", True),
            options=getattr(q, "options", []),
        )
        db.add(c_question)

    # JobQuestionPlan is deprecated: blueprint planning supersedes it
    await db.commit()

    # Refresh with relations loaded
    return await get_job(job.id, current_user=current_user, db=db)

@app.delete("/api/jobs/{job_id}")
async def delete_job(
    job_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(JobPosting).where(JobPosting.id == job_id)
    result = await db.execute(stmt)
    job = result.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    if job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job posting not found")
    # Delete dependent application trees explicitly so this remains deterministic
    # even when database-level cascade behavior differs between environments.
    application_ids = (
        await db.execute(
            select(JobApplication.id).where(JobApplication.job_id == job_id)
        )
    ).scalars().all()
    if application_ids:
        await db.execute(
            delete(CandidateApplication).where(CandidateApplication.job_id == job_id)
        )
        await db.execute(
            delete(JobApplication).where(JobApplication.id.in_(application_ids))
        )
    await db.delete(job)
    await db.commit()
    return {"message": "Job and all candidate applications deleted successfully", "id": job_id}

@app.post("/api/budget/preview")
async def preview_question_budget(payload: dict):
    duration = payload.get("duration_mins", 20)
    skills = payload.get("skills", [])
    return calculate_question_budget(duration, skills)


@app.post("/api/budget/blueprint/preview")
async def preview_blueprint_budget(payload: dict):
    from backend.app.budgeting import calculate_blueprint_section_budgets
    duration = payload.get("duration_mins", 20)
    skills = payload.get("skills", [])
    return calculate_blueprint_section_budgets(duration, skills)


@app.post("/api/jobs/suggest-skills")
async def suggest_skills_endpoint(
    payload: SuggestSkillsRequest,
    current_user: User = Depends(require_role("recruiter")),
):
    """Propose calibrated competencies and 5-level rubrics directly from a Job Description."""
    try:
        suggested = await suggest_skills_from_jd(
            job_title=payload.job_title,
            department=payload.department or "Engineering",
            seniority_level=payload.seniority_level or "Mid-Level (L4)",
            job_description=payload.job_description or "",
        )
        return {"skills": suggested}
    except Exception as exc:
        logger.warning("Suggest skills failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to suggest skills: {exc}"
        )


@app.get("/api/jobs/{job_id}/blueprint")
async def get_job_blueprint_endpoint(
    job_id: str,
    version: Optional[int] = None,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve active or latest blueprint for a job, enforcing ownership and candidate-safe redaction."""
    job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
    j_res = await db.execute(job_stmt)
    job = j_res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    is_recruiter = current_user and current_user.role == "recruiter"
    if is_recruiter and job.recruiter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this job's blueprint."
        )

    bp = await get_job_blueprint(db, job_id, version=version)
    if not bp and version is None:
        try:
            bp = await ensure_job_blueprint(db, job_id)
        except Exception as exc:
            logger.warning("Auto-creation of blueprint for legacy job %s failed: %s", job_id, exc)

    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found for this job")

    data = serialize_blueprint(bp, current_job=job)

    # Candidate-safe redaction: if not recruiter, redact internal rubric expectations, probes, and triggers
    if not is_recruiter:
        for sec in data.get("sections", []):
            sec["expectations"] = []
            sec["target_rubric_tier"] = None
            sec["questions"] = [
                q for q in sec.get("questions", [])
                if q.get("question_role") not in {"probe"}
            ]
            for q in sec.get("questions", []):
                q["trigger_condition"] = None
                q["target_expectation_ids"] = []

    return data


@app.post("/api/jobs/{job_id}/blueprint/generate")
async def generate_blueprint_for_job_endpoint(
    job_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    """Launch background generation for a Job Interview Blueprint, returning 202 Accepted with polling tracking."""
    job_stmt = (
        select(JobPosting)
        .where(JobPosting.id == job_id)
        .options(selectinload(JobPosting.skills))
    )
    res = await db.execute(job_stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    # Security check: Recruiter must own the job
    if job.recruiter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to generate a blueprint for this job."
        )

    # Check if a task is already running
    existing_task = _ACTIVE_BLUEPRINT_TASKS.get(job_id)
    if existing_task and existing_task.status == "in_progress":
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "in_progress",
                "job_id": job_id,
                "progress": existing_task.progress,
                "current_stage": existing_task.current_stage,
                "section_progress": existing_task.section_progress,
                "stage_timings": existing_task.stage_timings,
                "message": "Blueprint generation is already in progress.",
            }
        )

    skills_data = [
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

    task = BlueprintGenerationTask(job_id)
    _ACTIVE_BLUEPRINT_TASKS[job_id] = task

    asyncio.create_task(
        _run_blueprint_generation_background(
            job_id=job.id,
            job_title=job.job_title,
            seniority_level=job.seniority_level or "mid",
            duration_mins=job.interview_duration_mins or 20,
            skills_data=skills_data,
            job_description=job.job_description or "",
            task=task,
        )
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "in_progress",
            "job_id": job_id,
            "progress": task.progress,
            "current_stage": task.current_stage,
            "section_progress": task.section_progress,
            "stage_timings": task.stage_timings,
            "message": "Blueprint generation started in background.",
        }
    )


@app.get("/api/jobs/{job_id}/blueprint/generate/status")
async def get_blueprint_generation_status_endpoint(
    job_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    """Poll live background progress, stages, and section completion for blueprint generation."""
    job_stmt = (
        select(JobPosting)
        .where(JobPosting.id == job_id)
        .options(selectinload(JobPosting.skills))
    )
    res = await db.execute(job_stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    if job.recruiter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this job's blueprint status."
        )

    task = _ACTIVE_BLUEPRINT_TASKS.get(job_id)
    if task:
        return {
            "status": task.status,
            "progress": task.progress,
            "current_stage": task.current_stage,
            "section_progress": task.section_progress,
            "stage_timings": task.stage_timings,
            "blueprint": task.blueprint,
            "error": task.error,
            "errors": task.errors,
            "can_retry": task.can_retry,
        }

    # If no in-memory task, check if active/latest blueprint exists in DB
    bp = await get_job_blueprint(db, job_id)
    if bp:
        return {
            "status": "completed",
            "progress": 1.0,
            "current_stage": "completed",
            "section_progress": {},
            "stage_timings": bp.generation_stages_ms or {},
            "blueprint": serialize_blueprint(bp, current_job=job),
            "error": None,
            "errors": [],
            "can_retry": False,
        }

    return {
        "status": "idle",
        "progress": 0.0,
        "current_stage": "idle",
        "section_progress": {},
        "stage_timings": {},
        "blueprint": None,
        "error": None,
        "errors": [],
        "can_retry": True,
    }


@app.put("/api/jobs/{job_id}/blueprint/{blueprint_id}")
async def update_job_blueprint_endpoint(
    job_id: str,
    blueprint_id: str,
    payload: BlueprintUpdatePayload,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a blueprint.
    Copy-on-write: editing an approved blueprint automatically creates a new draft version.
    Re-runs validator and updates validation report.
    """
    job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
    res = await db.execute(job_stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    if job.recruiter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this blueprint."
        )

    try:
        updated_bp = await update_or_fork_job_blueprint(
            db=db,
            job_id=job_id,
            blueprint_id=blueprint_id,
            updated_sections=payload.sections,
            user_id=current_user.id,
        )
        return serialize_blueprint(updated_bp, current_job=job)
    except Exception as exc:
        logger.error("Error updating blueprint %s: %s", blueprint_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/jobs/{job_id}/blueprint/sections/{section_id}/regenerate")
async def regenerate_blueprint_section_endpoint(
    job_id: str,
    section_id: str,
    blueprint_id: str = Body(..., embed=True),
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    """Regenerate a single skill section using AI structured output and update/fork the blueprint."""
    job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
    res = await db.execute(job_stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    if job.recruiter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this blueprint."
        )

    try:
        updated_bp = await regenerate_blueprint_section(
            db=db,
            job_id=job_id,
            blueprint_id=blueprint_id,
            section_id=section_id,
            user_id=current_user.id,
        )
        return serialize_blueprint(updated_bp, current_job=job)
    except Exception as exc:
        logger.error("Error regenerating section %s: %s", section_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/jobs/{job_id}/blueprint/approve")
async def approve_job_blueprint_endpoint(
    job_id: str,
    payload: BlueprintApprovalRequest,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    """Approve a blueprint version, enforcing validation gates, and make it active for the job."""
    job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
    res = await db.execute(job_stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    if job.recruiter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to approve a blueprint for this job."
        )

    try:
        bp = await approve_job_blueprint(
            db=db,
            job_id=job_id,
            blueprint_id=payload.blueprint_id,
            user_id=current_user.id,
            confirmed_warnings=payload.confirmed_warnings,
        )
        return serialize_blueprint(bp, current_job=job)
    except ValueError as exc:
        err_msg = str(exc)
        needs_confirm = "must be confirmed" in err_msg or "warnings" in err_msg
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": err_msg, "needs_confirmation": needs_confirm}
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/jobs/{job_id}/blueprint/versions")
async def list_job_blueprint_versions_endpoint(
    job_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    """List all version history for a job blueprint, enforcing ownership."""
    job_stmt = select(JobPosting).where(JobPosting.id == job_id)
    res = await db.execute(job_stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    if job.recruiter_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this job's blueprint history."
        )

    bps = await list_job_blueprint_versions(db, job_id)
    return [
        {
            "id": bp.id,
            "version": bp.version,
            "status": bp.status,
            "created_at": bp.created_at,
            "approved_at": bp.approved_at,
            "total_duration_mins": bp.total_duration_mins,
            "active_skill_mins": bp.active_skill_mins,
            "is_stale": bp.is_stale,
        }
        for bp in bps
    ]



# ---------------------------------------------------------
# Authentication & User Management Endpoints
# ---------------------------------------------------------

@app.post("/api/auth/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check if user already exists
    stmt = select(User).where(User.email.ilike(payload.email.strip()))
    result = await db.execute(stmt)
    existing = result.scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists. Please sign in instead."
        )

    target_role = payload.role.lower() if payload.role in ["recruiter", "candidate"] else "candidate"

    # Enforce company requirement for recruiters
    if target_role == "recruiter" and (not payload.company_name or not payload.company_name.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company name is required for recruiter registration."
        )

    hashed_pwd = hash_password(payload.password)
    user = User(
        email=payload.email.strip().lower(),
        password_hash=hashed_pwd,
        full_name=payload.full_name.strip(),
        role=target_role,
        company_name=payload.company_name.strip() if payload.company_name else None,
        headline=payload.headline.strip() if payload.headline else None,
        auth_provider="local"
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "name": user.full_name
    })
    return TokenResponse(access_token=token, token_type="bearer", user=user)


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.email.ilike(payload.email.strip()))
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password. Please check your credentials."
        )

    # Enforce role matching if specified
    if payload.role and user.role != payload.role.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This account is registered as a {user.role.capitalize()}. Please select the {user.role.capitalize()} sign-in portal."
        )

    token = create_access_token({
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "name": user.full_name
    })
    return TokenResponse(access_token=token, token_type="bearer", user=user)


@app.post("/api/interview-sessions", response_model=None, status_code=status.HTTP_201_CREATED)
async def create_interview_session(
    payload: InterviewSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app_stmt = (
        select(JobApplication)
        .where(JobApplication.id == payload.application_id, JobApplication.job_id == payload.job_id)
        .options(selectinload(JobApplication.job))
    )
    application = (await db.execute(app_stmt)).scalars().first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "candidate" and application.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "recruiter" and application.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    session = InterviewSession(
        application_id=payload.application_id,
        job_id=payload.job_id,
        status="scheduled",
        total_questions_planned=payload.total_questions_planned,
        duration_planned_mins=payload.duration_planned_mins,
        gemini_model_used=(
            "gemini-3.5-flash"
            if payload.gemini_model_used.startswith("gemini-2.5")
            else payload.gemini_model_used
        ),
        system_prompt_snapshot=payload.system_prompt_snapshot
    )
    db.add(session)
    await db.commit()

    stmt = (
        select(InterviewSession)
        .options(
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.application),
            selectinload(InterviewSession.job),
        )
        .where(InterviewSession.id == session.id)
    )
    res = await db.execute(stmt)
    created_session = res.scalars().first()
    if current_user.role == "candidate":
        return CandidateInterviewSessionResponse.model_validate(
            created_session
        ).model_dump(mode="json")
    return InterviewSessionResponse.model_validate(created_session).model_dump(mode="json")


@app.get("/api/applications/{application_id}/interview-session", response_model=None)
async def get_application_interview_session(
    application_id: str,
    current_user: User = Depends(require_role("candidate")),
    db: AsyncSession = Depends(get_db),
):
    """Return the generated candidate-safe session, or an actionable pipeline status."""
    application = await get_application_with_relations(application_id, db)
    if not application or application.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    session_stmt = (
        select(InterviewSession)
        .where(InterviewSession.application_id == application_id)
        .options(
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.application),
            selectinload(InterviewSession.job),
        )
        .order_by(InterviewSession.created_at.desc())
    )
    session = (await db.execute(session_stmt)).scalars().first()
    if not session:
        if application.job and application.job.active_blueprint_id:
            from backend.app.services.interview.plan_materializer import materialize_blueprint_session_plan
            new_sess = InterviewSession(
                application_id=application_id,
                job_id=application.job_id,
                status="scheduled",
                duration_planned_mins=application.job.interview_duration_mins or 20,
                gemini_model_used=os.getenv("GEMINI_MODEL_LIVE", "gemini-3.5-flash-lite"),
            )
            db.add(new_sess)
            await db.flush()
            await materialize_blueprint_session_plan(new_sess, db)
            await db.commit()
            session = new_sess
        else:
            run_stmt = (
                select(InterviewGenerationRun)
                .where(InterviewGenerationRun.application_id == application_id)
                .order_by(InterviewGenerationRun.created_at.desc())
            )
            run = (await db.execute(run_stmt)).scalars().first()
            if run and run.status == "failed":
                raise HTTPException(
                    status_code=422,
                    detail=f"Interview question generation failed: {run.failure_reason or 'unknown error'}",
                )
            raise HTTPException(
                status_code=409,
                detail="Interview questions are still being generated. Refresh shortly.",
            )

    return CandidateInterviewSessionResponse.model_validate(session).model_dump(mode="json")


@app.post("/api/applications/{application_id}/interview-generation", status_code=status.HTTP_202_ACCEPTED)
async def trigger_application_interview_generation(
    application_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_role("candidate")),
    db: AsyncSession = Depends(get_db),
):
    application = await get_application_with_relations(application_id, db)
    if not application or application.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    if not application.resume or not application.resume.file_data:
        raise HTTPException(status_code=422, detail="Upload a resume before preparing the interview.")
    if application.resume.file_type != "pdf":
        raise HTTPException(
            status_code=422,
            detail="Interview preparation currently requires a PDF resume. Upload a PDF to this application.",
        )
    background_tasks.add_task(_run_candidate_personalization, application_id)
    return {"status": "accepted", "message": "Interview personalization and plan preparation started. Refresh in a moment."}


@app.post("/api/interview-sessions/{session_id}/start", response_model=None)
async def start_interview_session(
    session_id: str,
    current_user: User = Depends(require_role("candidate")),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.application),
            selectinload(InterviewSession.job),
        )
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session or not session.application or session.application.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview session not found")
    try:
        if session.status == SessionState.SCHEDULED.value:
            session.status = transition_session(session.status, SessionState.PREFLIGHT)
        if session.status in (SessionState.PREFLIGHT.value, SessionState.PAUSED.value):
            session.status = transition_session(session.status, SessionState.IN_PROGRESS)
            if not session.started_at:
                session.started_at = datetime.utcnow()
            await record_audit(
                db,
                current_user,
                "interview.session_started",
                application_id=session.application_id,
                job_id=session.job_id,
                session_id=session.id,
            )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response_stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session.id)
        .options(
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.application),
            selectinload(InterviewSession.job),
        )
    )
    response_session = (await db.execute(response_stmt)).scalars().first()
    return CandidateInterviewSessionResponse.model_validate(response_session).model_dump(mode="json")


@app.get("/api/interview-sessions/{session_id}", response_model=None)
async def get_interview_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(InterviewSession)
        .options(
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.application),
            selectinload(InterviewSession.job),
        )
        .where(InterviewSession.id == session_id)
    )
    res = await db.execute(stmt)
    session = res.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    owns_application = (
        session.application
        and (
            (current_user.role == "candidate" and session.application.candidate_id == current_user.id)
            or (current_user.role == "recruiter" and session.job.recruiter_id == current_user.id)
        )
    )
    if not owns_application:
        raise HTTPException(status_code=404, detail="Interview session not found")
    if current_user.role == "candidate":
        return CandidateInterviewSessionResponse.model_validate(session).model_dump(mode="json")
    return InterviewSessionResponse.model_validate(session).model_dump(mode="json")


@app.post("/api/interview-sessions/{session_id}/transcript-turns", response_model=InterviewTranscriptTurnResponse)
async def append_transcript_turn(
    session_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(selectinload(InterviewSession.application), selectinload(InterviewSession.job))
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    if not (
        (current_user.role == "candidate" and session.application.candidate_id == current_user.id)
        or (current_user.role == "recruiter" and session.job.recruiter_id == current_user.id)
    ):
        raise HTTPException(status_code=404, detail="Interview session not found")
    text_value = str(payload.get("text", "")).strip()
    if not text_value:
        raise HTTPException(status_code=400, detail="Transcript text is required")
    max_stmt = select(InterviewTranscriptTurn.sequence_number).where(
        InterviewTranscriptTurn.session_id == session_id
    ).order_by(InterviewTranscriptTurn.sequence_number.desc())
    last_sequence = (await db.execute(max_stmt)).scalars().first()
    expected_sequence = (last_sequence if last_sequence is not None else -1) + 1
    requested_sequence = payload.get("sequence_number", expected_sequence)
    if requested_sequence != expected_sequence:
        raise HTTPException(
            status_code=409,
            detail=f"Transcript sequence must be {expected_sequence}",
        )
    turn = InterviewTranscriptTurn(
        session_id=session_id,
        question_id=payload.get("question_id"),
        turn_type=payload.get("turn_type", "candidate_answer"),
        speaker=payload.get("speaker", "candidate"),
        text=text_value,
        spoken_text=payload.get("spoken_text"),
        was_interrupted=bool(payload.get("was_interrupted", False)),
        audio_ref=None,
        stt_confidence=payload.get("stt_confidence"),
        stt_final_ms=payload.get("stt_final_ms"),
        llm_ttft_ms=payload.get("llm_ttft_ms"),
        tts_first_audio_ms=payload.get("tts_first_audio_ms"),
        total_response_ms=payload.get("total_response_ms"),
        sequence_number=expected_sequence,
    )
    db.add(turn)
    await record_audit(
        db,
        current_user,
        "interview.answer_recorded",
        application_id=session.application_id,
        job_id=session.job_id,
        session_id=session.id,
        metadata={"question_id": payload.get("question_id")},
    )
    await db.commit()
    await db.refresh(turn)
    return turn


@app.post("/api/interview-sessions/webrtc/probe")
async def webrtc_probe_offer(
    payload: dict = Body(...),
):
    try:
        answer = await interview_manager.handle_probe_offer(payload)
        return answer
    except Exception as e:
        logger.error(f"Error handling WebRTC probe offer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/interview-sessions/webrtc/probe")
async def webrtc_probe_patch(
    payload: dict = Body(...),
):
    try:
        await interview_manager.handle_probe_patch(payload)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error handling WebRTC probe patch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/interview-sessions/{session_id}/webrtc")
async def webrtc_session_offer(
    session_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.application),
            selectinload(InterviewSession.job).selectinload(JobPosting.question_plans),
        )
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    is_authorized = (
        (current_user.role == "candidate" and (
            (session.application and session.application.candidate_id == current_user.id)
            or (session.application and session.application.email and session.application.email.lower() == current_user.email.lower())
        ))
        or (current_user.role in ("recruiter", "admin") and (
            session.job and session.job.recruiter_id == current_user.id or current_user.role == "admin"
        ))
    )
    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized for this session")

    active_questions = sorted(
        [q for q in (session.questions or []) if q.superseded_at is None],
        key=lambda q: q.question_index,
    )
    questions_data = [
        {
            "id": q.id,
            "question_index": q.question_index,
            "question_text": q.question_text,
            "skill_id": q.skill_id,
            "skill_name": q.skill_name,
            "skill_category": q.skill_category,
            "priority_tier": q.priority_tier or "P0",
            "expected_key_points": q.expected_key_points or [],
            "follow_up_depth_allowed": q.follow_up_depth_allowed,
            "follow_up_count": q.follow_up_count,
            "candidate_answer_transcript": q.candidate_answer_transcript,
            "question_state": q.question_state or "not_started",
            "coverage_status": q.coverage_status or {},
            "evidence_turn_ids": q.evidence_turn_ids or [],
        }
        for q in active_questions
    ]
    candidate_name = (session.application.full_name if session.application else None) or "Candidate"
    job = session.job
    role_title = (job.job_title if job else None) or "Engineer"
    max_depth = getattr(job, "max_followup_depth", 1) or 1
    duration_mins = float(session.duration_planned_mins or getattr(job, "interview_duration_mins", 20) or 20)
    allow_grace = bool(getattr(job, "allow_grace_extension", True))
    pacing_strictness = getattr(job, "pacing_strictness", "Balanced") or "Balanced"
    integrity_policy_tier = getattr(job, "integrity_policy_tier", "Moderate") or "Moderate"

    skill_time_allocations = {}
    if job and job.question_plans:
        for p in job.question_plans:
            if p.skill_name and p.time_allocation_minutes:
                skill_time_allocations[p.skill_name.casefold()] = float(p.time_allocation_minutes)

    job_public_fields = _public_job_payload(job) if job else {"job_title": role_title}
    candidate_hour = payload.get("candidate_local_hour")
    if candidate_hour is None and isinstance(payload.get("requestData"), dict):
        candidate_hour = payload["requestData"].get("candidate_local_hour")

    logger.info(
        f"=== [WebRTC Session Offer] Candidate '{candidate_name}' establishing WebRTC room "
        f"for session {session_id} (hour={candidate_hour}) ==="
    )

    try:
        answer = await interview_manager.handle_offer(
            session_id=session_id,
            request_dict=payload,
            candidate_name=candidate_name,
            role_title=role_title,
            questions=questions_data,
            candidate_local_hour=candidate_hour,
            max_followup_depth=max_depth,
            duration_planned_mins=duration_mins,
            allow_grace_extension=allow_grace,
            pacing_strictness=pacing_strictness,
            skill_time_allocations_mins=skill_time_allocations,
            interviewer_brief=session.interviewer_brief or session.system_prompt_snapshot or "",
            job_public_fields=job_public_fields,
            application_id=session.application_id,
            integrity_policy_tier=integrity_policy_tier,
            speech_speed=float(session.speech_speed or 1.0),
            captions_enabled=bool(session.captions_enabled if session.captions_enabled is not None else True),
        )
        return answer
    except InterviewerBusyError as busy_err:
        raise HTTPException(status_code=429, detail=str(busy_err))
    except Exception as e:
        logger.error(f"Error handling WebRTC session offer for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/interview-sessions/{session_id}/webrtc")
async def webrtc_session_patch(
    session_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await interview_manager.handle_patch(session_id, payload)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error handling WebRTC candidate patch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/interview-sessions/{session_id}/begin")
async def begin_interview_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(selectinload(InterviewSession.application))
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session or not session.application:
        raise HTTPException(status_code=404, detail="Interview session not found")

    owns_session = (
        (session.application.candidate_id == current_user.id)
        or (session.application.email and session.application.email.lower() == current_user.email.lower())
        or current_user.role in ("recruiter", "admin")
    )
    if not owns_session:
        raise HTTPException(status_code=403, detail="Not authorized for this session")

    logger.info(f"=== [Begin Interview Request] Candidate explicitly started live interview for session {session_id} ===")
    if session.status != "paused":
        session.current_phase = InterviewPhase.GREETING.value
        await db.commit()

    try:
        await interview_manager.begin_session(session_id)
    except KeyError as e:
        logger.warning(f"Begin session notice: {e}")
        raise HTTPException(
            status_code=409,
            detail="WebRTC live connection is still establishing. Please wait a moment and try again."
        )
    return {"status": "begun", "phase": session.current_phase or InterviewPhase.GREETING.value}


@app.post("/api/interview-sessions/{session_id}/repeat-question")
async def repeat_interview_question(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Repeat the current question without consuming a follow-up (Part G2)."""
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(selectinload(InterviewSession.application), selectinload(InterviewSession.questions))
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    try:
        repeated_text = await interview_manager.repeat_question(session_id)
        return {"status": "repeated", "text": repeated_text}
    except KeyError:
        active_qs = sorted(
            [q for q in (session.questions or []) if q.superseded_at is None],
            key=lambda q: q.question_index,
        )
        idx = min(session.current_question_index or 0, max(0, len(active_qs) - 1))
        fallback_text = active_qs[idx].question_text if active_qs else "Please tell me about your background."
        return {"status": "repeated", "text": fallback_text}


@app.patch("/api/interview-sessions/{session_id}/settings")
async def update_interview_session_settings(
    session_id: str,
    payload: InterviewSessionSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update speech_speed, captions_enabled, or recording_consent (Part F3, G1, G3)."""
    stmt = select(InterviewSession).where(InterviewSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    if payload.speech_speed is not None:
        session.speech_speed = float(payload.speech_speed)
    if payload.captions_enabled is not None:
        session.captions_enabled = bool(payload.captions_enabled)
    if payload.recording_consent is not None:
        # Recording remains OFF by default unless INTERVIEW_RECORDING_ENABLED=true
        recording_env = os.getenv("INTERVIEW_RECORDING_ENABLED", "false").lower() in {"1", "true", "yes"}
        session.recording_consent = bool(payload.recording_consent and recording_env)

    await db.commit()
    await interview_manager.update_session_settings(
        session_id=session_id,
        speech_speed=payload.speech_speed,
        captions_enabled=payload.captions_enabled,
    )
    return {
        "session_id": session.id,
        "speech_speed": session.speech_speed,
        "captions_enabled": session.captions_enabled,
        "recording_consent": session.recording_consent,
        "recording_enabled": os.getenv("INTERVIEW_RECORDING_ENABLED", "false").lower() in {"1", "true", "yes"},
    }


@app.post("/api/interview-sessions/{session_id}/integrity-events", response_model=InterviewIntegrityEventResponse)
async def create_integrity_event(
    session_id: str,
    payload: InterviewIntegrityEventCreate,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record client-side proctoring / integrity signals scaled by job policy tier (Part F1, F2)."""
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(selectinload(InterviewSession.job))
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    policy_tier = (session.job.integrity_policy_tier if session.job else None) or "Moderate"
    tier_lower = policy_tier.lower()
    ev_type = (payload.event_type or "unknown").strip().lower()

    if ev_type in {"prompt_injection", "multiple_faces", "paste"}:
        severity = "high" if tier_lower != "relaxed" else "medium"
    elif ev_type in {"camera_blocked", "no_face", "fullscreen_exit"}:
        severity = "high" if tier_lower == "strict" else ("medium" if tier_lower == "moderate" else "low")
    else:
        severity = "medium" if tier_lower == "strict" else "low"

    event = InterviewIntegrityEvent(
        session_id=session.id,
        application_id=session.application_id,
        event_type=ev_type,
        severity=severity,
        policy_tier=policy_tier,
        details_json=payload.details_json or {},
        created_at=datetime.utcnow(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@app.get("/api/interview-sessions/{session_id}/integrity-events", response_model=List[InterviewIntegrityEventResponse])
async def list_integrity_events(
    session_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(InterviewIntegrityEvent)
        .where(InterviewIntegrityEvent.session_id == session_id)
        .order_by(InterviewIntegrityEvent.created_at.asc())
    )
    return (await db.execute(stmt)).scalars().all()


@app.get("/api/interview-sessions/{session_id}/expectation-coverage")
async def get_session_expectation_coverage_endpoint(
    session_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve expectation coverage tracking progress for a session (recruiter only)."""
    return await get_session_expectation_coverage(db, session_id)


@app.post("/api/interview-sessions/{session_id}/feedback", response_model=InterviewFeedbackResponse)
async def submit_interview_feedback(
    session_id: str,
    payload: InterviewFeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit post-interview 1-5 rating and optional comment (Part G5)."""
    stmt = select(InterviewSession).where(InterviewSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    fb = InterviewFeedback(
        session_id=session.id,
        application_id=session.application_id,
        candidate_id=current_user.id,
        rating=payload.rating,
        comment=(payload.comment or "").strip() or None,
        created_at=datetime.utcnow(),
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return fb


@app.get("/api/interview-sessions/{session_id}/live-status")
async def get_interview_live_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(selectinload(InterviewSession.application), selectinload(InterviewSession.job))
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    mgr_status = interview_manager.get_session_status(session_id)
    return {
        "session_id": session.id,
        "status": session.status,
        "current_phase": session.current_phase or "greeting",
        "live_status": mgr_status,
    }


@app.post("/api/interview-sessions/{session_id}/end")
async def end_interview_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(selectinload(InterviewSession.application))
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    session.status = "completed"
    session.current_phase = "completed"
    session.completed_at = datetime.utcnow()

    if not session.is_practice:
        if session.application:
            session.application.status = "interview_completed"
        if session.application_id:
            await db.execute(
                update(JobApplication)
                .where(JobApplication.id == session.application_id)
                .values(status="interview_completed")
            )

    actor_email = current_user.email if current_user else "candidate"
    await record_audit(
        db,
        current_user,
        "interview.ended",
        session_id=session.id,
        application_id=session.application_id,
        metadata={"ended_by": actor_email},
    )
    await db.commit()

    # Clean up runner in live_interview_manager
    await interview_manager.cleanup_session(session_id)

    # Trigger post-interview Judge evaluation in background
    if background_tasks is not None and not session.is_practice:
        background_tasks.add_task(_run_evaluation_for_session, session.id)

    return {
        "status": "completed",
        "session_id": session.id,
        "application_id": session.application_id,
        "message": "Interview session ended and marked as completed.",
    }


@app.post("/api/candidate/practice-interview")
async def create_practice_interview(
    current_user: User = Depends(require_role("candidate")),
    db: AsyncSession = Depends(get_db),
):
    """Create a short 2-question practice interview on a generic role so candidates can warm up (Part G4)."""
    # Find any active job or create a generic practice job
    job_stmt = select(JobPosting).order_by(JobPosting.created_at.desc()).limit(1)
    job = (await db.execute(job_stmt)).scalars().first()
    if not job:
        job = JobPosting(
            job_title="Practice Software Engineer",
            department="Engineering",
            job_description="Practice interview environment for candidates.",
            seniority_level="Mid-Level (L4)",
            interview_duration_mins=5,
            status="practice",
        )
        db.add(job)
        await db.flush()

    # Create or reuse a practice application for this candidate
    app_stmt = select(JobApplication).where(
        JobApplication.candidate_id == current_user.id,
        JobApplication.status == "practice",
    )
    practice_app = (await db.execute(app_stmt)).scalars().first()
    if not practice_app:
        practice_app = JobApplication(
            job_id=job.id,
            candidate_id=current_user.id,
            full_name=current_user.full_name,
            email=current_user.email,
            status="practice",
            self_reported_experience_years=3.0,
            fit_pitch="Practice interview session",
        )
        db.add(practice_app)
        await db.flush()

    brief = (
        "=== CANDIDLY PRACTICE INTERVIEW BRIEF ===\n"
        "Role: Practice Software Engineer (Warm-up Session)\n"
        "Strict Voice Rules:\n"
        "1. Speak 1-2 short sentences maximum. Plain spoken English only.\n"
        "2. Ask at most ONE question per turn."
    )
    session = InterviewSession(
        application_id=practice_app.id,
        job_id=job.id,
        status="scheduled",
        total_questions_planned=2,
        duration_planned_mins=5,
        gemini_model_used=os.getenv("GEMINI_MODEL_LIVE", "gemini-3.5-flash-lite"),
        system_prompt_snapshot=brief,
        interviewer_brief=brief,
        is_practice=True,
    )
    db.add(session)
    await db.flush()

    practice_questions = [
        (
            "System Design",
            "Tell me about a system or feature you built recently that you're proud of, and one technical trade-off you made.",
            ["Concrete architecture or feature description", "Trade-off explained"],
        ),
        (
            "Problem Solving",
            "Describe a tricky production bug or performance bottleneck you diagnosed and how you verified the fix.",
            ["Root-cause debugging approach", "Verification or monitoring"],
        ),
    ]
    for idx, (sname, qtext, kps) in enumerate(practice_questions):
        db.add(
            InterviewQuestion(
                session_id=session.id,
                question_index=idx,
                skill_name=sname,
                skill_category="Practice",
                priority_tier="P0",
                question_text=qtext,
                expected_key_points=kps,
                follow_up_depth_allowed=1,
                question_state="not_started",
                coverage_status={kp: "uncovered" for kp in kps},
                evidence_turn_ids=[],
            )
        )
    await db.commit()

    refreshed = (
        await db.execute(
            select(InterviewSession)
            .where(InterviewSession.id == session.id)
            .options(selectinload(InterviewSession.questions))
        )
    ).scalars().first()
    return CandidateInterviewSessionResponse.model_validate(refreshed).model_dump(mode="json")


@app.get("/api/admin/audit-logs", response_model=List[AuditEventResponse])
async def get_audit_logs(
    x_admin_key: Optional[str] = Header(default=None),
    event_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    configured_key = os.getenv("ADMIN_API_KEY")
    if not configured_key:
        raise HTTPException(status_code=503, detail="Admin audit access is not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, configured_key):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    stmt = select(AuditEvent)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    stmt = stmt.order_by(AuditEvent.created_at.desc()).limit(min(max(limit, 1), 500))
    return (await db.execute(stmt)).scalars().all()


@app.get("/api/auth/me", response_model=UserResponse)
async def get_me(
    current_user: Optional[User] = Depends(get_optional_current_user),
    email: Optional[str] = None,
    user_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    if current_user:
        return current_user
    if user_id:
        stmt = select(User).where(User.id == user_id)
    elif email:
        stmt = select(User).where(User.email.ilike(email.strip()))
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ---------------------------------------------------------
# Candidate Portal & Application Endpoints
# ---------------------------------------------------------

@app.get("/api/candidate/applications", response_model=List[CandidateApplicationPublicResponse])
async def list_candidate_applications(
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve applications for the candidate.
    NEVER automatically applies candidate to any job. Returns empty list if no applications submitted.
    """
    target_user = current_user if (current_user and current_user.role == "candidate") else None
    if target_user is None and (user_id or email):
        user_stmt = select(User)
        if user_id:
            user_stmt = user_stmt.where(User.id == user_id)
        elif email:
            user_stmt = user_stmt.where(User.email.ilike(email))
        candidate_lookup = (await db.execute(user_stmt)).scalars().first()
        if candidate_lookup and candidate_lookup.role == "candidate":
            target_user = candidate_lookup

    if target_user is None:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Missing Bearer token.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Candidate privileges required.",
        )

    stmt = (
        select(JobApplication)
        .options(
            selectinload(JobApplication.job).selectinload(JobPosting.skills),
            selectinload(JobApplication.job).selectinload(JobPosting.certifications),
            selectinload(JobApplication.job).selectinload(JobPosting.custom_questions),
            selectinload(JobApplication.job).selectinload(JobPosting.question_plans),
            selectinload(JobApplication.resume),
            selectinload(JobApplication.discrepancy_flags),
            selectinload(JobApplication.id_verification),
        )
        .where(JobApplication.status != "practice")
        .order_by(JobApplication.applied_at.desc())
    )

    cand_conditions = [JobApplication.candidate_id == target_user.id]
    if target_user.email:
        cand_conditions.append(JobApplication.email.ilike(target_user.email))
    stmt = stmt.where(or_(*cand_conditions))

    result = await db.execute(stmt)
    applications = result.scalars().all()
    payload = []
    for app in applications:
        run = (
            await db.execute(
                select(InterviewGenerationRun)
                .where(InterviewGenerationRun.application_id == app.id)
                .order_by(InterviewGenerationRun.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        session = (
            await db.execute(
                select(InterviewSession)
                .where(InterviewSession.application_id == app.id, InterviewSession.is_practice == False)
                .order_by(InterviewSession.created_at.desc())
                .limit(1)
            )
        ).scalars().first()

        is_completed = bool(
            app.status in ["interview_completed", "completed", "under_review", "interviewed", "hired"]
            or (session and session.status == "completed")
        )

        # Auto-heal if application was submitted and generation failed due to transient 503
        gen_status = run.status if run else None
        if not is_completed and app.status == "submitted" and gen_status == "failed" and app.resume:
            asyncio.create_task(_run_candidate_personalization(app.id))
            gen_status = "running"

        is_ready = bool(
            run
            and run.status == "succeeded"
            and session
            and session.status in ["scheduled", "preflight", "in_progress", "paused"]
            and not is_completed
        )

        candidate_summary = None
        feedback_submitted = False
        if session:
            ev = (
                await db.execute(
                    select(InterviewEvaluation.candidate_summary)
                    .where(InterviewEvaluation.session_id == session.id)
                    .order_by(InterviewEvaluation.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            candidate_summary = ev
            fb = (
                await db.execute(
                    select(InterviewFeedback.id)
                    .where(InterviewFeedback.session_id == session.id)
                    .limit(1)
                )
            ).scalars().first()
            feedback_submitted = fb is not None

        payload.append({
            "id": app.id,
            "job_id": app.job_id,
            "status": app.status,
            "applied_at": app.applied_at,
            "job": _public_job_payload(app.job),
            "interview_generation_status": gen_status,
            "interview_ready": is_ready,
            "interview_completed": is_completed,
            "interview_session_status": session.status if session else None,
            "interview_session_id": session.id if session else None,
            "candidate_summary": candidate_summary,
            "feedback_submitted": feedback_submitted,
        })
    return payload


@app.delete("/api/candidate/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_candidate_application(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Withdraw candidate application and completely wipe out all data regarding that candidate ID:
    Removes transcript turns, questions, sessions, evaluations, integrity events, feedback,
    generation runs, resumes, discrepancy flags, identity verifications, audit logs, and application records.
    """
    conditions = [JobApplication.candidate_id == current_user.id]
    if current_user.email:
        conditions.append(JobApplication.email.ilike(current_user.email))
    if application_id and application_id not in ("all", "undefined", "null"):
        conditions.append(JobApplication.id == application_id)

    app_stmt = select(JobApplication).where(or_(*conditions))
    res = await db.execute(app_stmt)
    candidate_apps = res.scalars().all()
    target_app_ids = [app.id for app in candidate_apps]
    if application_id and application_id not in ("all", "undefined", "null") and application_id not in target_app_ids:
        target_app_ids.append(application_id)

    session_ids = []
    if target_app_ids:
        sessions_stmt = select(InterviewSession).where(InterviewSession.application_id.in_(target_app_ids))
        sessions_res = await db.execute(sessions_stmt)
        sessions = sessions_res.scalars().all()
        session_ids = [s.id for s in sessions]

        for s in sessions:
            await interview_manager.cleanup_session(s.id)

        if session_ids:
            eval_ids = (
                await db.execute(
                    select(InterviewEvaluation.id).where(InterviewEvaluation.session_id.in_(session_ids))
                )
            ).scalars().all()
            if eval_ids:
                await db.execute(
                    delete(InterviewSkillScore).where(InterviewSkillScore.evaluation_id.in_(eval_ids))
                )
            await db.execute(
                delete(InterviewEvaluation).where(InterviewEvaluation.session_id.in_(session_ids))
            )
            await db.execute(
                delete(InterviewIntegrityEvent).where(InterviewIntegrityEvent.session_id.in_(session_ids))
            )
            await db.execute(
                delete(InterviewFeedback).where(InterviewFeedback.session_id.in_(session_ids))
            )
            await db.execute(
                delete(InterviewTranscriptTurn).where(InterviewTranscriptTurn.session_id.in_(session_ids))
            )
            await db.execute(
                delete(InterviewQuestion).where(InterviewQuestion.session_id.in_(session_ids))
            )
            await db.execute(
                delete(InterviewSession).where(InterviewSession.id.in_(session_ids))
            )

        gen_runs = (
            await db.execute(
                select(InterviewGenerationRun.id).where(InterviewGenerationRun.application_id.in_(target_app_ids))
            )
        ).scalars().all()
        if gen_runs:
            await db.execute(
                delete(InterviewQuestion).where(InterviewQuestion.generation_run_id.in_(gen_runs))
            )
        await db.execute(
            delete(InterviewGenerationRun).where(InterviewGenerationRun.application_id.in_(target_app_ids))
        )

        resumes_stmt = select(CandidateResume).where(CandidateResume.application_id.in_(target_app_ids))
        resumes = (await db.execute(resumes_stmt)).scalars().all()
        for resume in resumes:
            if resume.original_file_path and os.path.exists(resume.original_file_path):
                try:
                    os.remove(resume.original_file_path)
                except Exception as e:
                    logger.warning(f"Failed to remove resume file on disk: {e}")
        await db.execute(
            delete(CandidateResume).where(CandidateResume.application_id.in_(target_app_ids))
        )

        await db.execute(
            delete(ResumeDiscrepancyFlag).where(ResumeDiscrepancyFlag.application_id.in_(target_app_ids))
        )
        await db.execute(
            delete(CandidateIdVerification).where(CandidateIdVerification.application_id.in_(target_app_ids))
        )

    audit_conditions = [AuditEvent.actor_id == current_user.id]
    if target_app_ids:
        audit_conditions.append(AuditEvent.application_id.in_(target_app_ids))
    if session_ids:
        audit_conditions.append(AuditEvent.session_id.in_(session_ids))
    await db.execute(
        delete(AuditEvent).where(or_(*audit_conditions))
    )

    legacy_conditions = [CandidateApplication.user_id == current_user.id]
    if target_app_ids:
        legacy_conditions.append(CandidateApplication.id.in_(target_app_ids))
    await db.execute(
        delete(CandidateApplication).where(or_(*legacy_conditions))
    )

    if target_app_ids:
        await db.execute(
            delete(JobApplication).where(JobApplication.id.in_(target_app_ids))
        )

    await db.commit()
    logger.info(f"Successfully wiped all data for candidate {current_user.id} ({current_user.email})")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/candidate/apply/{job_id}", response_model=JobApplicationResponse)
async def apply_to_job(
    job_id: str,
    payload: dict = None,
    current_user: User = Depends(require_role("candidate")),
    db: AsyncSession = Depends(get_db)
):
    candidate_id = current_user.id
    
    # Verify job exists
    job_stmt = select(JobPosting).where(JobPosting.id == job_id)
    j_res = await db.execute(job_stmt)
    job = j_res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    # Enforce blueprint approval gate (Checkpoint R2/R3)
    await _enrich_jobs_with_blueprint_status([job], db)
    if not getattr(job, "accepts_applications", False):
        detail = "This job is not accepting applications yet. Requires an approved, up-to-date interview blueprint."
        if getattr(job, "blueprint_is_stale", False):
            detail = "This job is not accepting applications yet. The interview blueprint is stale and requires recruiter re-approval."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    candidate_email = current_user.email
    candidate_name = current_user.full_name

    # Check existing application
    app_stmt = select(JobApplication).where(
        JobApplication.job_id == job_id,
        (JobApplication.candidate_id == candidate_id) | (JobApplication.email.ilike(candidate_email))
    )
    existing_res = await db.execute(app_stmt)
    existing = existing_res.scalars().first()
    if existing:
        return await get_application_with_relations(existing.id, db)

    new_app = JobApplication(
        job_id=job_id,
        candidate_id=candidate_id,
        full_name=candidate_name,
        email=candidate_email,
        status="submitted",
        self_reported_experience_years=(payload or {}).get("self_reported_experience_years", 3.0),
        fit_pitch=(payload or {}).get("fit_pitch", "Excited to apply and interview for this role."),
        expected_salary=(payload or {}).get("expected_salary", job.salary_range_min or 120000.0),
        expected_salary_currency=job.salary_currency or "USD"
    )
    db.add(new_app)
    await db.commit()

    # Trigger candidate personalization and blueprint session plan materialization off-request (R3.1/R3.2)
    asyncio.create_task(_run_candidate_personalization(new_app.id))

    return await get_application_with_relations(new_app.id, db)


# ---------------------------------------------------------
# Candidate Application Pipeline Endpoints
# ---------------------------------------------------------

async def get_application_with_relations(app_id: str, db: AsyncSession) -> Optional[JobApplication]:
    db.expire_all()
    stmt = (
        select(JobApplication)
        .where(JobApplication.id == app_id)
        .options(
            selectinload(JobApplication.job).selectinload(JobPosting.skills),
            selectinload(JobApplication.job).selectinload(JobPosting.certifications),
            selectinload(JobApplication.job).selectinload(JobPosting.custom_questions),
            selectinload(JobApplication.job).selectinload(JobPosting.question_plans),
            selectinload(JobApplication.resume),
            selectinload(JobApplication.discrepancy_flags),
            selectinload(JobApplication.id_verification),
            selectinload(JobApplication.candidate),
        )
    )
    result = await db.execute(stmt)
    return result.scalars().first()


@app.post("/api/applications", response_model=None, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: JobApplicationCreate,
    current_user: User = Depends(require_role("candidate")),
    db: AsyncSession = Depends(get_db)
):
    # Verify target job exists
    job_stmt = (
        select(JobPosting)
        .where(JobPosting.id == payload.job_id)
        .options(
            selectinload(JobPosting.skills),
            selectinload(JobPosting.certifications),
            selectinload(JobPosting.custom_questions),
        )
    )
    j_res = await db.execute(job_stmt)
    job = j_res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Target job posting not found")

    await _enrich_jobs_with_blueprint_status([job], db)
    if not job.accepts_applications:
        detail = "This job is not accepting applications yet. Requires an approved, up-to-date interview blueprint."
        if getattr(job, "blueprint_is_stale", False):
            detail = "This job is not accepting applications yet. The interview blueprint is stale and requires recruiter re-approval."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    candidate_id = current_user.id

    app = JobApplication(
        job_id=payload.job_id,
        candidate_id=candidate_id,
        full_name=payload.full_name.strip(),
        email=payload.email.strip().lower(),
        phone=payload.phone.strip() if payload.phone else None,
        linkedin_url=payload.linkedin_url.strip() if payload.linkedin_url else None,
        portfolio_url=payload.portfolio_url.strip() if payload.portfolio_url else None,
        status="submitted",
        self_reported_experience_years=payload.self_reported_experience_years,
        fit_pitch=payload.fit_pitch,
        expected_salary=payload.expected_salary,
        expected_salary_currency=payload.expected_salary_currency or "USD"
    )
    db.add(app)
    await db.commit()
    created = await get_application_with_relations(app.id, db)
    return _candidate_application_payload(created)


@app.post("/api/applications/{application_id}/resume")
async def upload_application_resume(
    application_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "candidate" and app.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "recruiter" and (not app.job or app.job.recruiter_id != current_user.id):
        raise HTTPException(status_code=404, detail="Application not found")

    # 1. Validate extension
    filename = file.filename or "resume.pdf"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ['.pdf', '.docx', '.txt']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Only PDF, DOCX, and TXT files are accepted."
        )

    # 2. Read and enforce 10MB limit
    content = await file.read()
    max_bytes = 10 * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds hard limit of 10 MB ({len(content) / (1024*1024):.2f} MB provided)."
        )

    # 3. In-memory encoding for Gemini API multimodal ingestion
    file_base64_str = base64.b64encode(content).decode("utf-8")

    # 4. Execute Real Parsing Pipeline in-memory (PDF / DOCX / TXT + Apple Vision OCR fallback)
    try:
        extracted_text, file_type, ocr_used = extract_text_from_file(content, filename=filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {str(e)}")

    # 5. Extract Structured Data
    structured_data = parse_structured_resume_data(extracted_text)

    # Auto-populate application coordinates if empty
    contact_info = structured_data.get("contact_info", {})
    if not app.phone and contact_info.get("phone"):
        app.phone = contact_info["phone"]
    if not app.linkedin_url and contact_info.get("linkedin"):
        app.linkedin_url = contact_info["linkedin"]
    if not app.portfolio_url and (contact_info.get("portfolio") or contact_info.get("github")):
        app.portfolio_url = contact_info.get("portfolio") or contact_info.get("github")
    if not app.fit_pitch and structured_data.get("summary"):
        app.fit_pitch = structured_data["summary"]
    if (not app.self_reported_experience_years or app.self_reported_experience_years == 0.0) and structured_data.get("total_experience_years"):
        app.self_reported_experience_years = structured_data["total_experience_years"]

    # 6. Automated Discrepancy Detection
    flags_data = detect_discrepancies(
        self_reported_years=app.self_reported_experience_years,
        structured_data=structured_data,
        job=app.job
    )

    # 7. Persist CandidateResume record directly into PostgreSQL (BYTEA & Base64)
    resume_stmt = select(CandidateResume).where(CandidateResume.application_id == application_id)
    r_res = await db.execute(resume_stmt)
    existing_resume = r_res.scalars().first()

    download_endpoint = f"/api/applications/{application_id}/resume/file"

    if existing_resume:
        existing_resume.original_file_path = download_endpoint
        existing_resume.original_file_name = filename
        existing_resume.file_type = file_type
        existing_resume.file_size_bytes = len(content)
        existing_resume.file_data = content
        existing_resume.file_base64 = file_base64_str
        existing_resume.parsed_text = extracted_text
        existing_resume.parsed_structured_data = structured_data
        existing_resume.ocr_used = ocr_used
        existing_resume.parsing_status = "success"
    else:
        new_resume = CandidateResume(
            application_id=application_id,
            original_file_path=download_endpoint,
            original_file_name=filename,
            file_type=file_type,
            file_size_bytes=len(content),
            file_data=content,
            file_base64=file_base64_str,
            parsed_text=extracted_text,
            parsed_structured_data=structured_data,
            ocr_used=ocr_used,
            parsing_status="success"
        )
        db.add(new_resume)

    # 8. Update Discrepancy Flags (clear old, add current)
    del_stmt = select(ResumeDiscrepancyFlag).where(ResumeDiscrepancyFlag.application_id == application_id)
    flags_res = await db.execute(del_stmt)
    for existing_flag in flags_res.scalars().all():
        await db.delete(existing_flag)

    for fd in flags_data:
        flag = ResumeDiscrepancyFlag(
            application_id=application_id,
            field_name=fd["field_name"],
            candidate_stated_value=fd["candidate_stated_value"],
            resume_derived_value=fd["resume_derived_value"],
            flag_reason=fd["flag_reason"],
            reviewed_by_recruiter=False
        )
        db.add(flag)

    await db.commit()

    updated_app = await get_application_with_relations(application_id, db)
    return {
        "status": "success",
        "file_name": filename,
        "file_type": file_type,
        "ocr_used": ocr_used,
        "parsed_structured_data": structured_data,
        "parsed_text": extracted_text[:1000],
        "discrepancy_flags": [
            {
                "id": f.id,
                "field_name": f.field_name,
                "candidate_stated_value": f.candidate_stated_value,
                "resume_derived_value": f.resume_derived_value,
                "flag_reason": f.flag_reason,
                "reviewed_by_recruiter": f.reviewed_by_recruiter
            } for f in updated_app.discrepancy_flags
        ]
    }


@app.get("/api/applications/{application_id}/parsed-resume")
async def get_parsed_resume(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await get_application_with_relations(application_id, db)
    if not app or (
        current_user.role == "candidate" and app.candidate_id != current_user.id
    ) or (
        current_user.role == "recruiter" and (not app.job or app.job.recruiter_id != current_user.id)
    ):
        raise HTTPException(status_code=404, detail="Application not found")
    stmt = select(CandidateResume).where(CandidateResume.application_id == application_id)
    res = await db.execute(stmt)
    resume = res.scalars().first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found for this application")

    return {
        "original_file_name": resume.original_file_name,
        "original_file_path": resume.original_file_path,
        "file_type": resume.file_type,
        "file_base64": resume.file_base64,
        "file_download_url": f"/api/applications/{application_id}/resume/file",
        "ocr_used": resume.ocr_used,
        "parsed_structured_data": resume.parsed_structured_data,
        "parsed_text": resume.parsed_text
    }


@app.get("/api/applications/{application_id}/resume/file")
async def get_resume_file(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await get_application_with_relations(application_id, db)
    if not app or (
        current_user.role == "candidate" and app.candidate_id != current_user.id
    ) or (
        current_user.role == "recruiter" and (not app.job or app.job.recruiter_id != current_user.id)
    ):
        raise HTTPException(status_code=404, detail="Application not found")
    stmt = select(CandidateResume).where(CandidateResume.application_id == application_id)
    res = await db.execute(stmt)
    resume = res.scalars().first()
    if not resume or not resume.file_data:
        raise HTTPException(status_code=404, detail="Resume file not found in database")

    media_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain"
    }
    media_type = media_types.get(resume.file_type, "application/octet-stream")
    return Response(
        content=bytes(resume.file_data),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{resume.original_file_name or "resume.pdf"}"'
        }
    )


@app.patch("/api/applications/{application_id}/parsed-resume", response_model=None)
async def update_parsed_resume(
    application_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "candidate" and app.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "recruiter" and (not app.job or app.job.recruiter_id != current_user.id):
        raise HTTPException(status_code=404, detail="Application not found")

    if not app.resume:
        raise HTTPException(status_code=400, detail="No resume uploaded yet for this application")

    # Update structured data from candidate corrections
    corrected_data = payload.get("parsed_structured_data")
    if corrected_data:
        app.resume.parsed_structured_data = corrected_data
        c_info = corrected_data.get("contact_info", {})
        if c_info.get("phone") and not app.phone:
            app.phone = c_info["phone"]
        if c_info.get("linkedin") and not app.linkedin_url:
            app.linkedin_url = c_info["linkedin"]
        if (c_info.get("portfolio") or c_info.get("github")) and not app.portfolio_url:
            app.portfolio_url = c_info.get("portfolio") or c_info.get("github")
        if corrected_data.get("summary") and not app.fit_pitch:
            app.fit_pitch = corrected_data["summary"]

    # If self-reported experience was updated
    if "self_reported_experience_years" in payload:
        app.self_reported_experience_years = float(payload["self_reported_experience_years"])

    # Re-run automated discrepancy check against corrected values
    flags_data = detect_discrepancies(
        self_reported_years=app.self_reported_experience_years,
        structured_data=app.resume.parsed_structured_data,
        job=app.job
    )

    # Clear previous flags and store re-calculated flags
    del_stmt = select(ResumeDiscrepancyFlag).where(ResumeDiscrepancyFlag.application_id == application_id)
    flags_res = await db.execute(del_stmt)
    for f in flags_res.scalars().all():
        await db.delete(f)

    for fd in flags_data:
        new_flag = ResumeDiscrepancyFlag(
            application_id=application_id,
            field_name=fd["field_name"],
            candidate_stated_value=fd["candidate_stated_value"],
            resume_derived_value=fd["resume_derived_value"],
            flag_reason=fd["flag_reason"],
            reviewed_by_recruiter=False
        )
        db.add(new_flag)

    await db.commit()
    updated = await get_application_with_relations(application_id, db)
    return _candidate_application_payload(updated) if current_user.role == "candidate" else updated


@app.post("/api/applications/{application_id}/verification", response_model=None)
async def save_id_verification(
    application_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "candidate" and app.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "recruiter" and (not app.job or app.job.recruiter_id != current_user.id):
        raise HTTPException(status_code=404, detail="Application not found")

    live_photo_data = payload.get("live_photo")
    gov_id_data = payload.get("government_id")

    if not live_photo_data:
        raise HTTPException(status_code=400, detail="Live webcam photo snapshot is required")

    # Store photo as data URL directly in PostgreSQL
    live_photo_val = live_photo_data if live_photo_data.startswith("data:") else f"data:image/jpeg;base64,{live_photo_data}"

    # Optional government ID
    gov_id_val = None
    if gov_id_data and len(gov_id_data) > 10:
        gov_id_val = gov_id_data if gov_id_data.startswith("data:") else f"data:image/jpeg;base64,{gov_id_data}"

    # Upsert verification record directly in PostgreSQL
    stmt = select(CandidateIdVerification).where(CandidateIdVerification.application_id == application_id)
    res = await db.execute(stmt)
    existing_verif = res.scalars().first()

    if existing_verif:
        existing_verif.live_photo_path = live_photo_val
        existing_verif.government_id_path = gov_id_val or existing_verif.government_id_path
        existing_verif.captured_at = datetime.utcnow()
        existing_verif.verification_status = "pending"
    else:
        new_verif = CandidateIdVerification(
            application_id=application_id,
            live_photo_path=live_photo_val,
            government_id_path=gov_id_val,
            captured_at=datetime.utcnow(),
            verification_status="pending"
        )
        db.add(new_verif)

    await db.commit()
    updated = await get_application_with_relations(application_id, db)
    return _candidate_application_payload(updated) if current_user.role == "candidate" else updated


@app.patch("/api/applications/{application_id}/submit", response_model=None)
async def finalize_application_submission(
    application_id: str,
    payload: Optional[JobApplicationUpdate] = None,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "candidate" and app.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "recruiter" and (not app.job or app.job.recruiter_id != current_user.id):
        raise HTTPException(status_code=404, detail="Application not found")

    if app.job:
        await _enrich_jobs_with_blueprint_status([app.job], db)
        if not getattr(app.job, "accepts_applications", False):
            detail = "This job is not accepting applications yet. Requires an approved, up-to-date interview blueprint."
            if getattr(app.job, "blueprint_is_stale", False):
                detail = "This job is not accepting applications yet. The interview blueprint is stale and requires recruiter re-approval."
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    if payload:
        if payload.full_name: app.full_name = payload.full_name
        if payload.email: app.email = payload.email
        if payload.phone is not None: app.phone = payload.phone
        if payload.linkedin_url is not None: app.linkedin_url = payload.linkedin_url
        if payload.portfolio_url is not None: app.portfolio_url = payload.portfolio_url
        if payload.self_reported_experience_years is not None: app.self_reported_experience_years = payload.self_reported_experience_years
        if payload.fit_pitch is not None: app.fit_pitch = payload.fit_pitch
        if payload.expected_salary is not None: app.expected_salary = payload.expected_salary
        if payload.expected_salary_currency is not None: app.expected_salary_currency = payload.expected_salary_currency

    app.status = "submitted"
    app.applied_at = datetime.utcnow()
    await db.commit()
    if background_tasks is not None:
        # FastAPI BackgroundTasks keeps the HTTP response independent of Gemini latency.
        # A durable queue (Celery/RQ/etc.) is the production upgrade when volume grows.
        background_tasks.add_task(_run_candidate_personalization, app.id)
    finalized = await get_application_with_relations(application_id, db)
    return _candidate_application_payload(finalized) if current_user.role == "candidate" else finalized


@app.get("/api/jobs/{job_id}/applications", response_model=None)
async def list_job_applications(
    job_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    job_stmt = select(JobPosting).where(
        JobPosting.id == job_id,
        JobPosting.recruiter_id == current_user.id
    )
    job_result = await db.execute(job_stmt)
    if not job_result.scalars().first():
        raise HTTPException(status_code=404, detail="Job posting not found")

    stmt = (
        select(JobApplication)
        .where(JobApplication.job_id == job_id, JobApplication.status != "practice")
        .options(
            selectinload(JobApplication.resume),
            selectinload(JobApplication.discrepancy_flags),
            selectinload(JobApplication.id_verification),
            selectinload(JobApplication.candidate),
            selectinload(JobApplication.interview_sessions).selectinload(InterviewSession.evaluations).selectinload(InterviewEvaluation.skill_scores),
            selectinload(JobApplication.interview_sessions).selectinload(InterviewSession.integrity_events),
        )
        .order_by(JobApplication.applied_at.desc())
    )
    result = await db.execute(stmt)
    apps = result.scalars().all()

    enriched = []
    for app in apps:
        base_dict = JobApplicationResponse.model_validate(app).model_dump(mode="json")
        sessions = sorted(
            [s for s in (app.interview_sessions or []) if not s.is_practice],
            key=lambda s: s.created_at or datetime.min,
            reverse=True,
        )
        latest_session = sessions[0] if sessions else None
        latest_eval = None
        if latest_session and latest_session.evaluations:
            evals = sorted(
                latest_session.evaluations,
                key=lambda e: e.created_at or datetime.min,
                reverse=True,
            )
            latest_eval = evals[0]

        integrity_events = latest_session.integrity_events if latest_session else []
        skill_levels = {}
        if latest_eval and latest_eval.skill_scores:
            for sc in latest_eval.skill_scores:
                skill_levels[sc.skill_name] = sc.level

        base_dict["session_id"] = latest_session.id if latest_session else None
        base_dict["session_status"] = latest_session.status if latest_session else None
        base_dict["interview_completed"] = bool(
            (latest_session and latest_session.status == "completed")
            or app.status in ("interview_completed", "interviewed", "hired")
        )
        base_dict["overall_score"] = latest_eval.overall_score if latest_eval else None
        base_dict["verdict"] = latest_eval.verdict if latest_eval else None
        base_dict["insufficient_evidence"] = bool(latest_eval.insufficient_evidence) if latest_eval else False
        base_dict["p0_not_assessed_skills"] = (latest_eval.p0_not_assessed_skills or []) if latest_eval else []
        base_dict["skill_levels"] = skill_levels
        base_dict["integrity_flags_count"] = len(integrity_events or [])
        base_dict["discrepancy_count"] = len(app.discrepancy_flags or [])
        base_dict["unresolved_discrepancies"] = sum(
            1 for f in (app.discrepancy_flags or []) if not f.reviewed_by_recruiter
        )
        enriched.append(base_dict)

    return enriched


@app.get("/api/applications/{application_id}", response_model=None)
async def get_application(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    is_owner = (
        (current_user.role == "recruiter" and app.job and app.job.recruiter_id == current_user.id)
        or (current_user.role == "candidate" and app.candidate_id == current_user.id)
    )
    if not is_owner:
        raise HTTPException(status_code=404, detail="Application not found")
    if current_user.role == "candidate":
        return _candidate_application_payload(app)
    # Never expose the binary resume payload through ORM serialization.
    return JobApplicationResponse.model_validate(app)


@app.patch("/api/applications/{application_id}/discrepancies/{flag_id}", response_model=ResumeDiscrepancyFlagResponse)
async def review_discrepancy_flag(
    application_id: str,
    flag_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    application = await get_application_with_relations(application_id, db)
    if not application or not application.job or application.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    stmt = select(ResumeDiscrepancyFlag).where(
        ResumeDiscrepancyFlag.id == flag_id,
        ResumeDiscrepancyFlag.application_id == application_id
    )
    res = await db.execute(stmt)
    flag = res.scalars().first()
    if not flag:
        raise HTTPException(status_code=404, detail="Discrepancy flag not found")

    flag.reviewed_by_recruiter = not flag.reviewed_by_recruiter
    await db.commit()
    await db.refresh(flag)
    return flag


@app.patch("/api/applications/{application_id}/status", response_model=JobApplicationResponse)
async def update_application_status(
    application_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    new_status = payload.get("status")
    allowed_statuses = [
        "submitted",
        "under_review",
        "ready_for_interview",
        "interview_completed",
        "interviewed",
        "rejected",
        "hired",
    ]
    if not new_status or new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status '{new_status}'. Must be one of {allowed_statuses}")

    app = await get_application_with_relations(application_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if not app.job or app.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    app.status = new_status
    await db.commit()
    return await get_application_with_relations(application_id, db)


# ---------------------------------------------------------
# Recruiter Scorecard, Decision & Interview Plan Endpoints (Parts D & E)
# ---------------------------------------------------------

@app.get("/api/applications/{application_id}/scorecard")
async def get_application_scorecard(
    application_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Fetch complete recruiter scorecard: evaluation, skill scores, verbatim evidence, transcript, integrity events, feedback, and interview plan."""
    app = await get_application_with_relations(application_id, db)
    if not app or not app.job or app.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    session_stmt = (
        select(InterviewSession)
        .where(InterviewSession.application_id == application_id, InterviewSession.is_practice == False)
        .options(
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.transcript_turns),
            selectinload(InterviewSession.evaluations).selectinload(InterviewEvaluation.skill_scores),
            selectinload(InterviewSession.integrity_events),
            selectinload(InterviewSession.feedback_entries),
        )
        .order_by(InterviewSession.created_at.desc())
    )
    session = (await db.execute(session_stmt)).scalars().first()
    if not session:
        return {
            "application_id": application_id,
            "session": None,
            "evaluation": None,
            "questions": [],
            "transcript_turns": [],
            "integrity_events": [],
            "feedback": None,
            "recruiter_decision": app.recruiter_decision,
            "recruiter_notes": app.recruiter_notes,
            "decided_at": app.decided_at,
        }

    evaluation = None
    if session.evaluations:
        evaluation = sorted(session.evaluations, key=lambda e: e.created_at or datetime.min, reverse=True)[0]
    elif session.status == "completed" and session.transcript_turns:
        # Auto-evaluate completed session if not yet evaluated
        evaluation = await evaluate_interview_session(session.id, db)

    active_questions = sorted(
        [q for q in (session.questions or []) if q.superseded_at is None],
        key=lambda q: q.question_index,
    )
    turns = sorted(session.transcript_turns or [], key=lambda t: t.sequence_number)
    integrity = sorted(session.integrity_events or [], key=lambda ev: ev.created_at or datetime.min)
    feedback = session.feedback_entries[0] if session.feedback_entries else None

    return {
        "application_id": application_id,
        "session": InterviewSessionResponse.model_validate(session).model_dump(mode="json"),
        "evaluation": (
            InterviewEvaluationResponse.model_validate(evaluation).model_dump(mode="json")
            if evaluation
            else None
        ),
        "questions": [
            InterviewQuestionResponse.model_validate(q).model_dump(mode="json")
            for q in active_questions
        ],
        "transcript_turns": [
            InterviewTranscriptTurnResponse.model_validate(t).model_dump(mode="json")
            for t in turns
        ],
        "integrity_events": [
            InterviewIntegrityEventResponse.model_validate(ev).model_dump(mode="json")
            for ev in integrity
        ],
        "feedback": (
            InterviewFeedbackResponse.model_validate(feedback).model_dump(mode="json")
            if feedback
            else None
        ),
        "recruiter_decision": app.recruiter_decision,
        "recruiter_notes": app.recruiter_notes,
        "decided_at": app.decided_at,
    }


@app.post("/api/applications/{application_id}/evaluate", response_model=InterviewEvaluationResponse)
async def trigger_application_evaluation(
    application_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger or re-run the Evidence-Anchored Judge on the application's latest interview session."""
    app = await get_application_with_relations(application_id, db)
    if not app or not app.job or app.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    session = (
        await db.execute(
            select(InterviewSession)
            .where(InterviewSession.application_id == application_id, InterviewSession.is_practice == False)
            .order_by(InterviewSession.created_at.desc())
        )
    ).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="No interview session found for this application")

    evaluation = await evaluate_interview_session(session.id, db)
    return evaluation


@app.get("/api/applications/{application_id}/candidate-summary", response_model=CandidateSafeEvaluationSummary)
async def get_candidate_safe_summary(
    application_id: str,
    current_user: User = Depends(require_role("candidate")),
    db: AsyncSession = Depends(get_db),
):
    """Return a candidate-safe constructive summary without scores, rubric levels, or hiring verdict (Part D5)."""
    app = await get_application_with_relations(application_id, db)
    if not app or app.candidate_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    ev = (
        await db.execute(
            select(InterviewEvaluation)
            .where(InterviewEvaluation.application_id == application_id)
            .order_by(InterviewEvaluation.created_at.desc())
        )
    ).scalars().first()
    if not ev:
        raise HTTPException(status_code=404, detail="Summary is being prepared")

    return CandidateSafeEvaluationSummary(
        session_id=ev.session_id,
        application_id=application_id,
        candidate_summary=ev.candidate_summary,
        completed_at=ev.completed_at,
    )


@app.post("/api/applications/{application_id}/decision", response_model=JobApplicationResponse)
async def record_recruiter_decision(
    application_id: str,
    payload: RecruiterDecisionRequest,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Record recruiter hiring decision ('advance', 'hold', 'reject') and notes (Part E1)."""
    decision_clean = (payload.decision or "").strip().lower()
    if decision_clean not in {"advance", "hold", "reject"}:
        raise HTTPException(status_code=400, detail="Decision must be 'advance', 'hold', or 'reject'")

    app = await get_application_with_relations(application_id, db)
    if not app or not app.job or app.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    app.recruiter_decision = decision_clean
    app.recruiter_notes = (payload.notes or "").strip() or None
    app.decided_by = current_user.id
    app.decided_at = datetime.utcnow()

    if decision_clean == "advance":
        app.status = "hired"
    elif decision_clean == "reject":
        app.status = "rejected"
    else:
        app.status = "under_review"

    await record_audit(
        db,
        current_user,
        "recruiter.decision_recorded",
        application_id=app.id,
        job_id=app.job_id,
        metadata={"decision": decision_clean},
    )
    await db.commit()
    return await get_application_with_relations(application_id, db)


@app.get("/api/applications/{application_id}/interview-plan")
async def get_application_interview_plan(
    application_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Preview the generated interview question plan for a candidate (Part E3)."""
    app = await get_application_with_relations(application_id, db)
    if not app or not app.job or app.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    session = (
        await db.execute(
            select(InterviewSession)
            .where(InterviewSession.application_id == application_id, InterviewSession.is_practice == False)
            .options(selectinload(InterviewSession.questions))
            .order_by(InterviewSession.created_at.desc())
        )
    ).scalars().first()
    run = (
        await db.execute(
            select(InterviewGenerationRun)
            .where(InterviewGenerationRun.application_id == application_id)
            .order_by(InterviewGenerationRun.created_at.desc())
        )
    ).scalars().first()

    active_questions = (
        sorted(
            [q for q in (session.questions or []) if q.superseded_at is None],
            key=lambda q: q.question_index,
        )
        if session
        else []
    )
    return {
        "application_id": application_id,
        "session_id": session.id if session else None,
        "session_status": session.status if session else None,
        "generation_status": run.status if run else None,
        "model_name": run.model_name if run else None,
        "questions": [
            InterviewQuestionResponse.model_validate(q).model_dump(mode="json")
            for q in active_questions
        ],
    }


@app.patch("/api/applications/{application_id}/questions/{question_id}", response_model=InterviewQuestionResponse)
async def update_interview_question(
    application_id: str,
    question_id: str,
    payload: InterviewQuestionUpdateRequest,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Allow recruiter to edit question text, key points, priority, follow-up depth, or approval before interview (Part E3)."""
    app = await get_application_with_relations(application_id, db)
    if not app or not app.job or app.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    q = (
        await db.execute(select(InterviewQuestion).where(InterviewQuestion.id == question_id))
    ).scalars().first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    if payload.question_text is not None and payload.question_text.strip():
        q.question_text = payload.question_text.strip()
    if payload.expected_key_points is not None:
        cleaned_kps = [kp.strip() for kp in payload.expected_key_points if kp and kp.strip()]
        q.expected_key_points = cleaned_kps
        q.coverage_status = {kp: "uncovered" for kp in cleaned_kps}
    if payload.priority_tier is not None and payload.priority_tier in ("P0", "P1", "P2"):
        q.priority_tier = payload.priority_tier
    if payload.follow_up_depth_allowed is not None:
        q.follow_up_depth_allowed = max(0, min(3, int(payload.follow_up_depth_allowed)))
    if payload.approved_by_recruiter is not None:
        q.approved_by_recruiter = bool(payload.approved_by_recruiter)

    await db.commit()
    await db.refresh(q)
    return q


@app.post("/api/applications/{application_id}/interview-plan/approve")
async def approve_interview_plan(
    application_id: str,
    payload: Optional[InterviewPlanApprovalRequest] = None,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Approve all active questions in the application's interview plan (Part E3)."""
    app = await get_application_with_relations(application_id, db)
    if not app or not app.job or app.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")

    session = (
        await db.execute(
            select(InterviewSession)
            .where(InterviewSession.application_id == application_id, InterviewSession.is_practice == False)
            .options(selectinload(InterviewSession.questions))
            .order_by(InterviewSession.created_at.desc())
        )
    ).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    approved_flag = payload.approved if payload is not None else True
    active_questions = [q for q in (session.questions or []) if q.superseded_at is None]
    for q in active_questions:
        q.approved_by_recruiter = approved_flag

    await record_audit(
        db,
        current_user,
        "recruiter.interview_plan_approved",
        application_id=application_id,
        job_id=app.job_id,
        session_id=session.id,
        metadata={"approved": approved_flag, "question_count": len(active_questions)},
    )
    await db.commit()
    return {
        "status": "approved" if approved_flag else "unapproved",
        "session_id": session.id,
        "question_count": len(active_questions),
    }


@app.post("/api/applications/{application_id}/interview-plan/regenerate")
async def regenerate_interview_plan(
    application_id: str,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Force-regenerate the interview question plan for an application before the interview starts (Part E3)."""
    app = await get_application_with_relations(application_id, db)
    if not app or not app.job or app.job.recruiter_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    if not app.resume or not app.resume.file_data:
        raise HTTPException(status_code=422, detail="Application has no PDF resume uploaded")

    run = await generate_for_application(application_id, db, force=True)
    return await get_application_interview_plan(application_id, current_user=current_user, db=db)

