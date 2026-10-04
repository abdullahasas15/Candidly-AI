import os
import base64
from datetime import datetime
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form, Body, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from backend.app.database import engine, Base, get_db, AsyncSessionLocal
from backend.app.models import (
    JobPosting, JobSkill, JobCertification, JobCustomQuestion, JobQuestionPlan,
    User, CandidateApplication, JobApplication, CandidateResume, ResumeDiscrepancyFlag, CandidateIdVerification,
    InterviewSession, InterviewQuestion
)
from backend.app.schemas import (
    JobCreate, JobResponse, UserCreate, UserLogin, UserResponse, CandidateApplicationResponse,
    JobApplicationCreate, JobApplicationUpdate, JobApplicationResponse, JobApplicationListItem,
    CandidateResumeResponse, ResumeDiscrepancyFlagResponse, CandidateIdVerificationResponse,
    TokenResponse, InterviewSessionCreate, InterviewSessionResponse,
    InterviewQuestionCreate, InterviewQuestionResponse, CandidateApplicationPublicResponse
)
from backend.app.budgeting import calculate_question_budget
from backend.app.services.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_optional_current_user, require_role
)
from backend.app.services.resume_parser import (
    extract_text_from_file, parse_structured_resume_data, detect_discrepancies
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables & schema migrations
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
        ]
        for mig in migrations:
            try:
                await conn.execute(text(mig))
            except Exception:
                pass
    
    # Auto-seeding is disabled so user starts with a completely clean database
    yield
    await engine.dispose()

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
    }

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Candidly AI Platform Backend",
        "database": "Connected"
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
    jobs = result.scalars().all()
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
    if current_user and current_user.role == "recruiter":
        if job.recruiter_id != current_user.id:
            raise HTTPException(status_code=404, detail="Job posting not found")
        return job
    if job.status != "active":
        raise HTTPException(status_code=404, detail="Job posting not found")
    return _public_job_payload(job)

@app.post("/api/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    current_user: User = Depends(require_role("recruiter")),
    db: AsyncSession = Depends(get_db)
):
    # 1. Create JobPosting instance
    recruiter_id = current_user.id if current_user else None
    job = JobPosting(
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
    skill_dicts = []
    for s in payload.skills:
        skill = JobSkill(
            job_id=job.id,
            name=s.name,
            category=s.category,
            priority_tier=s.priority_tier,
            weight_percentage=s.weight_percentage,
            rubric_l1=s.rubric_l1,
            rubric_l2=s.rubric_l2,
            rubric_l3=s.rubric_l3,
            rubric_l4=s.rubric_l4,
            rubric_l5=s.rubric_l5,
        )
        db.add(skill)
        skill_dicts.append({
            "name": s.name,
            "category": s.category,
            "priority_tier": s.priority_tier,
            "weight_percentage": s.weight_percentage
        })

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

    # 4. Add Custom Questions
    for q in payload.custom_questions:
        c_question = JobCustomQuestion(
            job_id=job.id,
            question_text=q.question_text,
            category=q.category,
            difficulty_level=q.difficulty_level,
            expected_key_points=q.expected_key_points,
            priority_tier=q.priority_tier
        )
        db.add(c_question)

    # 5. Calculate and persist Question Plan via Mathematical Budgeting Algorithm
    budget = calculate_question_budget(payload.interview_duration_mins, skill_dicts)
    for alloc in budget["allocations"]:
        plan = JobQuestionPlan(
            job_id=job.id,
            skill_name=alloc["skill_name"],
            skill_priority=alloc["skill_priority"],
            allocated_questions=alloc["allocated_questions"],
            time_allocation_minutes=alloc["time_allocation_minutes"],
            weight_percentage=alloc["weight_percentage"],
            target_rubric_tier=alloc["target_rubric_tier"]
        )
        db.add(plan)

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
    await db.delete(job)
    await db.commit()
    return {"message": "Job deleted successfully", "id": job_id}

@app.post("/api/budget/preview")
async def preview_question_budget(payload: dict):
    duration = payload.get("duration_mins", 20)
    skills = payload.get("skills", [])
    return calculate_question_budget(duration, skills)


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


@app.post("/api/interview-sessions", response_model=InterviewSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_interview_session(
    payload: InterviewSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    session = InterviewSession(
        application_id=payload.application_id,
        job_id=payload.job_id,
        status="scheduled",
        total_questions_planned=payload.total_questions_planned,
        duration_planned_mins=payload.duration_planned_mins,
        gemini_model_used=payload.gemini_model_used,
        system_prompt_snapshot=payload.system_prompt_snapshot
    )
    db.add(session)
    await db.commit()

    stmt = (
        select(InterviewSession)
        .options(selectinload(InterviewSession.questions))
        .where(InterviewSession.id == session.id)
    )
    res = await db.execute(stmt)
    return res.scalars().first()


@app.get("/api/interview-sessions/{session_id}", response_model=InterviewSessionResponse)
async def get_interview_session(
    session_id: str,
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(InterviewSession)
        .options(selectinload(InterviewSession.questions))
        .where(InterviewSession.id == session_id)
    )
    res = await db.execute(stmt)
    session = res.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return session


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
    current_user: User = Depends(require_role("candidate")),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve applications for the candidate.
    NEVER automatically applies candidate to any job. Returns empty list if no applications submitted.
    """
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
        .order_by(JobApplication.applied_at.desc())
    )

    stmt = stmt.where(JobApplication.candidate_id == current_user.id)

    result = await db.execute(stmt)
    applications = result.scalars().all()
    return [
        {
            "id": app.id,
            "job_id": app.job_id,
            "status": app.status,
            "applied_at": app.applied_at,
            "job": _public_job_payload(app.job),
        }
        for app in applications
    ]


@app.post("/api/candidate/apply/{job_id}", response_model=JobApplicationResponse)
async def apply_to_job(
    job_id: str,
    payload: dict = None,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    candidate_id = (payload or {}).get("user_id") or (current_user.id if current_user else None)
    
    # Verify job exists
    job_stmt = select(JobPosting).where(JobPosting.id == job_id)
    j_res = await db.execute(job_stmt)
    job = j_res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")

    candidate_email = (payload or {}).get("email") or (current_user.email if current_user else "candidate@example.com")
    candidate_name = (payload or {}).get("full_name") or (current_user.full_name if current_user else "Applicant")

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


@app.post("/api/applications", response_model=JobApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: JobApplicationCreate,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify target job exists
    job_stmt = select(JobPosting).where(JobPosting.id == payload.job_id)
    j_res = await db.execute(job_stmt)
    job = j_res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Target job posting not found")

    candidate_id = payload.candidate_id or (current_user.id if current_user else None)

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
    return await get_application_with_relations(app.id, db)


@app.post("/api/applications/{application_id}/resume")
async def upload_application_resume(
    application_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
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
async def get_parsed_resume(application_id: str, db: AsyncSession = Depends(get_db)):
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
async def get_resume_file(application_id: str, db: AsyncSession = Depends(get_db)):
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


@app.patch("/api/applications/{application_id}/parsed-resume", response_model=JobApplicationResponse)
async def update_parsed_resume(
    application_id: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
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
    return await get_application_with_relations(application_id, db)


@app.post("/api/applications/{application_id}/verification", response_model=JobApplicationResponse)
async def save_id_verification(
    application_id: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
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
    return await get_application_with_relations(application_id, db)


@app.patch("/api/applications/{application_id}/submit", response_model=JobApplicationResponse)
async def finalize_application_submission(
    application_id: str,
    payload: Optional[JobApplicationUpdate] = None,
    db: AsyncSession = Depends(get_db)
):
    app = await get_application_with_relations(application_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

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
    return await get_application_with_relations(application_id, db)


@app.get("/api/jobs/{job_id}/applications", response_model=List[JobApplicationResponse])
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
        .where(JobApplication.job_id == job_id)
        .options(
            selectinload(JobApplication.resume),
            selectinload(JobApplication.discrepancy_flags),
            selectinload(JobApplication.id_verification),
            selectinload(JobApplication.candidate),
        )
        .order_by(JobApplication.applied_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@app.get("/api/applications/{application_id}", response_model=JobApplicationResponse)
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
    return app


@app.patch("/api/applications/{application_id}/discrepancies/{flag_id}", response_model=ResumeDiscrepancyFlagResponse)
async def review_discrepancy_flag(
    application_id: str,
    flag_id: str,
    db: AsyncSession = Depends(get_db)
):
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
    db: AsyncSession = Depends(get_db)
):
    new_status = payload.get("status")
    allowed_statuses = ["submitted", "under_review", "ready_for_interview", "interviewed", "rejected", "hired"]
    if not new_status or new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status '{new_status}'. Must be one of {allowed_statuses}")

    app = await get_application_with_relations(application_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.status = new_status
    await db.commit()
    return await get_application_with_relations(application_id, db)
