import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, JSON, LargeBinary
from sqlalchemy.orm import relationship
from backend.app.database import Base

class RoleTemplate(Base):
    __tablename__ = "role_templates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    role_key = Column(String(50), unique=True, index=True, nullable=False) # sde, ai_engineer, devops, data_engineer
    display_name = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    default_duration_mins = Column(Integer, default=30, nullable=False)
    default_interviewer_tone = Column(Text, nullable=True)
    default_pacing = Column(String(50), default="Balanced", nullable=False)
    suggested_certifications = Column(JSON, default=list, nullable=False)
    skills = Column(JSON, default=list, nullable=False)
    seniority_profiles = Column(JSON, default=dict, nullable=False)
    question_style_notes = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job_postings = relationship("JobPosting", back_populates="role_template")


class JobPosting(Base):
    __tablename__ = "job_postings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # 1. Role Identity & Metadata Fields
    role_key = Column(String(50), default="custom", nullable=False) # 'sde', 'ai_engineer', 'devops', 'data_engineer', 'custom'
    role_template_id = Column(String(36), ForeignKey("role_templates.id", ondelete="SET NULL"), nullable=True)
    role_template_version = Column(Integer, nullable=True)
    job_title = Column(String(255), nullable=False)
    department = Column(String(255), nullable=False)
    job_description = Column(Text, default="N/A", nullable=False)
    seniority_level = Column(String(100), nullable=False, default="mid") # entry, mid, senior, lead
    employment_type = Column(String(100), nullable=False, default="Full-Time") # Full-Time, Part-Time, Contract, Internship
    workplace_model = Column(String(100), nullable=False, default="Remote") # Remote, Hybrid, On-site
    permitted_locations = Column(JSON, default=list) # e.g. ["United States", "Canada", "Remote (EST/PST)"]
    
    # 2. Educational & Academic Qualification Metrics
    min_degree_level = Column(String(255), default="Bachelor's Degree (B.S. / B.E. / B.Tech)")
    degree_enforcement_type = Column(String(255), default="Equivalent Professional Experience Allowed")
    accepted_majors = Column(JSON, default=lambda: ["Computer Science", "Software Engineering", "Information Technology"])
    min_cgpa = Column(String(100), default="3.0 / 4.0")
    cgpa_strict_filter = Column(Boolean, default=False)
    grad_year_start = Column(Integer, nullable=True)
    grad_year_end = Column(Integer, nullable=True)

    # 3. Professional Experience Metrics
    total_experience_years = Column(Float, default=3.0)
    domain_experience_years = Column(Float, default=2.0)
    leadership_required = Column(Boolean, default=False)

    # 4. Session & AI Interviewer Policy Configuration
    interview_duration_mins = Column(Integer, default=20) # 15, 20, 30, 45, 60
    allow_grace_extension = Column(Boolean, default=True) # +5m toggle
    max_followup_depth = Column(Integer, default=1) # 1 or 2
    pacing_strictness = Column(String(255), default="Balanced") # Relaxed, Balanced, Aggressive
    interviewer_tone = Column(Text, default="Direct, technical, tech-lead caliber; probes for architectural trade-offs; warm but concise.")
    integrity_policy_tier = Column(String(255), default="Moderate") # Basic, Moderate, Strict

    # 5. Compensation & Location Budget
    salary_range_min = Column(Float, nullable=True)
    salary_range_max = Column(Float, nullable=True)
    salary_currency = Column(String(20), default="USD")

    recruiter_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    active_blueprint_id = Column(String(36), ForeignKey("interview_blueprints.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active") # active, draft, archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    role_template = relationship("RoleTemplate", back_populates="job_postings", foreign_keys=[role_template_id], lazy="selectin")
    recruiter = relationship("User", back_populates="posted_jobs", lazy="selectin")
    skills = relationship("JobSkill", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    certifications = relationship("JobCertification", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    custom_questions = relationship("JobCustomQuestion", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    question_plans = relationship("JobQuestionPlan", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    applications = relationship("JobApplication", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    blueprints = relationship("InterviewBlueprint", back_populates="job", cascade="all, delete-orphan", foreign_keys="[InterviewBlueprint.job_id]", lazy="selectin")
    active_blueprint = relationship("InterviewBlueprint", foreign_keys=[active_blueprint_id], post_update=True)

    @property
    def role_display_name(self) -> Optional[str]:
        if self.role_template and getattr(self.role_template, "display_name", None):
            return self.role_template.display_name
        if self.role_key and self.role_key != "custom":
            return self.role_key.replace("_", " ").title()
        return "Custom Role"



class JobSkill(Base):
    __tablename__ = "job_skills"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    template_skill_key = Column(String(50), nullable=True) # key from role template if applicable
    name = Column(String(100), nullable=False)
    category = Column(String(100), default="Core Technical") # Core Technical, Tooling, Architecture, Soft & Cultural
    priority_tier = Column(String(20), default="P0") # P0 Mandatory, P1 High, P2 Bonus
    weight_percentage = Column(Float, nullable=False) # e.g. 35.0
    target_level_min = Column(String(10), nullable=True) # e.g. L2, L3, L4
    target_level_max = Column(String(10), nullable=True) # e.g. L3, L4, L5
    source = Column(String(20), default="recruiter", nullable=False) # template, ai_suggested, recruiter

    # 5-Level Behavioral Rubric Anchors
    rubric_l1 = Column(Text, nullable=True) # Incompetent / Novice
    rubric_l2 = Column(Text, nullable=True) # Developing / Basic
    rubric_l3 = Column(Text, nullable=True) # Proficient / Target Baseline
    rubric_l4 = Column(Text, nullable=True) # Advanced / Strong
    rubric_l5 = Column(Text, nullable=True) # Expert / Exceptional

    job = relationship("JobPosting", back_populates="skills")


class JobCertification(Base):
    __tablename__ = "job_certifications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(150), nullable=False)
    issuing_org = Column(String(100), nullable=False)
    priority_tier = Column(String(20), default="P1") # P0 Mandatory, P1 Highly Preferred, P2 Bonus
    verification_required = Column(Boolean, default=False)

    job = relationship("JobPosting", back_populates="certifications")


class JobCustomQuestion(Base):
    __tablename__ = "job_custom_questions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    question_text = Column(Text, nullable=False)
    category = Column(String(100), default="Core Technical")
    difficulty_level = Column(String(50), default="Mid-Senior")
    expected_key_points = Column(JSON, default=list) # Array of 3-4 bullet points
    priority_tier = Column(String(20), default="P0")
    question_type = Column(String(50), default="text") # text, textarea, yes_no, single_choice
    is_required = Column(Boolean, default=True)
    options = Column(JSON, default=list) # Options for single_choice/multiple_choice

    job = relationship("JobPosting", back_populates="custom_questions")


class JobQuestionPlan(Base):
    """
    @deprecated: Retained for backward schema compatibility.
    Interview time allocation and question planning are now managed via
    backend/app/budgeting.py and InterviewBlueprint / BlueprintSection.
    """
    __tablename__ = "job_question_plans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    skill_name = Column(String(100), nullable=False)
    skill_priority = Column(String(20), default="P0")
    allocated_questions = Column(Integer, nullable=False)
    time_allocation_minutes = Column(Float, nullable=False)
    weight_percentage = Column(Float, nullable=False)
    target_rubric_tier = Column(String(100), default="L3-L4")

    job = relationship("JobPosting", back_populates="question_plans")


class InterviewBlueprint(Base):
    __tablename__ = "interview_blueprints"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    status = Column(String(20), default="draft", nullable=False) # draft, approved, archived
    total_duration_mins = Column(Integer, nullable=False, default=20)
    active_skill_mins = Column(Float, nullable=False, default=14.0)
    fixed_overhead_mins = Column(Float, nullable=False, default=6.0)
    approved_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    validation_report = Column(JSON, nullable=True)
    input_hash = Column(String(64), nullable=True)
    is_stale = Column(Boolean, default=False, nullable=False)
    generation_provider = Column(String(50), nullable=True) # gemini, tokenharbor
    generation_model = Column(String(100), nullable=True)
    generation_latency_ms = Column(Float, nullable=True)
    generation_stages_ms = Column(JSON, nullable=True)
    is_generated_with_backup = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("JobPosting", back_populates="blueprints", foreign_keys=[job_id])
    approver = relationship("User", foreign_keys=[approved_by])
    sections = relationship("BlueprintSection", back_populates="blueprint", cascade="all, delete-orphan", order_by="BlueprintSection.order_index", lazy="selectin")


class BlueprintSection(Base):
    __tablename__ = "blueprint_sections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    blueprint_id = Column(String(36), ForeignKey("interview_blueprints.id", ondelete="CASCADE"), nullable=False, index=True)
    order_index = Column(Integer, nullable=False)
    section_type = Column(String(50), nullable=False) # welcome, intro, skill, candidate_qa, closing
    title = Column(String(255), nullable=False)
    skill_id = Column(String(36), ForeignKey("job_skills.id", ondelete="SET NULL"), nullable=True)
    skill_name = Column(String(200), nullable=True)
    priority_tier = Column(String(20), nullable=True) # P0, P1, P2
    allocated_minutes = Column(Float, nullable=False)
    target_rubric_tier = Column(String(50), nullable=True) # L4-L5 Expert, L3-L4 Proficient
    welcome_script = Column(Text, nullable=True)
    closing_script = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    blueprint = relationship("InterviewBlueprint", back_populates="sections")
    skill = relationship("JobSkill")
    expectations = relationship("BlueprintExpectation", back_populates="section", cascade="all, delete-orphan", order_by="BlueprintExpectation.order_index", lazy="selectin")
    questions = relationship("BlueprintQuestion", back_populates="section", cascade="all, delete-orphan", order_by="BlueprintQuestion.order_index", lazy="selectin")


class BlueprintExpectation(Base):
    __tablename__ = "blueprint_expectations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id = Column(String(36), ForeignKey("blueprint_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    order_index = Column(Integer, nullable=False)
    expectation_text = Column(Text, nullable=False)
    source_rubric_level = Column(String(20), nullable=True) # L3, L4, L5
    importance = Column(String(20), default="core", nullable=False) # core, stretch
    created_at = Column(DateTime, default=datetime.utcnow)

    section = relationship("BlueprintSection", back_populates="expectations")
    coverages = relationship("SessionExpectationCoverage", back_populates="expectation", cascade="all, delete-orphan")


class BlueprintQuestion(Base):
    __tablename__ = "blueprint_questions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id = Column(String(36), ForeignKey("blueprint_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    order_index = Column(Integer, nullable=False)
    question_role = Column(String(30), nullable=False) # anchor, escalation, probe, intro_hook, custom
    question_text = Column(Text, nullable=False)
    trigger_condition = Column(Text, nullable=True)
    target_expectation_ids = Column(JSON, default=list) # [expectation_id, ...]
    word_count = Column(Integer, nullable=False, default=0)
    source = Column(String(20), default="llm", nullable=False) # llm, recruiter
    created_at = Column(DateTime, default=datetime.utcnow)

    section = relationship("BlueprintSection", back_populates="questions")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True) # Nullable for OAuth users
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="recruiter") # 'recruiter' or 'candidate'
    company_name = Column(String(150), nullable=True) # for recruiters
    headline = Column(String(200), nullable=True) # for candidates
    avatar_url = Column(String(500), nullable=True)
    auth_provider = Column(String(50), default="local") # 'local' or 'google'
    created_at = Column(DateTime, default=datetime.utcnow)

    posted_jobs = relationship("JobPosting", back_populates="recruiter", lazy="selectin")
    applications = relationship("CandidateApplication", back_populates="user", cascade="all, delete-orphan", lazy="selectin")
    job_applications = relationship("JobApplication", foreign_keys="[JobApplication.candidate_id]", back_populates="candidate", cascade="all, delete-orphan", lazy="selectin")



class CandidateApplication(Base):
    __tablename__ = "candidate_applications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), default="interview_ready") # applied, interview_ready, completed, under_review
    fit_score = Column(Float, nullable=True)
    applied_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="applications")
    job = relationship("JobPosting", lazy="selectin")


class JobApplication(Base):
    __tablename__ = "job_applications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    candidate_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    full_name = Column(String(150), nullable=False)
    email = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=True)
    linkedin_url = Column(String(255), nullable=True)
    portfolio_url = Column(String(255), nullable=True)

    status = Column(String(50), default="submitted") # submitted, under_review, ready_for_interview, interviewed, rejected, hired
    applied_at = Column(DateTime, default=datetime.utcnow)

    self_reported_experience_years = Column(Float, default=0.0)
    fit_pitch = Column(Text, nullable=True)
    expected_salary = Column(Float, nullable=True)
    expected_salary_currency = Column(String(10), default="USD")

    # Application Screening & Workday/LinkedIn Compliance
    screening_answers = Column(JSON, default=list) # [{ question_id, question_text, answer }]
    work_authorization = Column(String(100), default="Authorized") # Authorized, Requires Sponsorship, etc.
    visa_sponsorship_needed = Column(Boolean, default=False)

    # Recruiter Final Decision Fields (Human-in-the-loop)
    recruiter_decision = Column(String(50), nullable=True) # strong_hire, hire, lean_hire, no_hire, hold
    recruiter_notes = Column(Text, nullable=True)
    decided_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job = relationship("JobPosting", back_populates="applications", lazy="selectin")
    candidate = relationship("User", foreign_keys=[candidate_id], back_populates="job_applications", lazy="selectin")
    resume = relationship("CandidateResume", back_populates="application", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    discrepancy_flags = relationship("ResumeDiscrepancyFlag", back_populates="application", cascade="all, delete-orphan", lazy="selectin")
    id_verification = relationship("CandidateIdVerification", back_populates="application", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    interview_sessions = relationship("InterviewSession", back_populates="application", cascade="all, delete-orphan", lazy="selectin")
    generation_runs = relationship("InterviewGenerationRun", back_populates="application", cascade="all, delete-orphan", lazy="selectin")
    personalization = relationship("CandidatePersonalization", back_populates="application", uselist=False, cascade="all, delete-orphan", lazy="selectin")


class CandidateResume(Base):
    __tablename__ = "candidate_resumes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False)

    original_file_path = Column(String(500), nullable=True) # Direct API endpoint e.g. /api/applications/{app_id}/resume/file
    original_file_name = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False) # pdf, docx, txt
    file_size_bytes = Column(Integer, nullable=False)

    # In-Database PDF/Document Storage (Zero filesystem dependency)
    file_data = Column(LargeBinary, nullable=True) # Raw PDF bytes in PostgreSQL (BYTEA)
    file_base64 = Column(Text, nullable=True) # Base64 string for instant LLM/Gemini API prompt transmission

    parsed_text = Column(Text, nullable=True)
    parsed_structured_data = Column(JSON, default=dict) # companies, roles, dates, degrees, skills, total_experience_years
    ocr_used = Column(Boolean, default=False)
    parsing_status = Column(String(50), default="pending") # pending, success, failed
    created_at = Column(DateTime, default=datetime.utcnow)

    application = relationship("JobApplication", back_populates="resume")


class ResumeDiscrepancyFlag(Base):
    __tablename__ = "resume_discrepancy_flags"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False)

    field_name = Column(String(100), nullable=False) # e.g. "years_of_experience", "degree"
    candidate_stated_value = Column(String(255), nullable=True)
    resume_derived_value = Column(String(255), nullable=True)
    flag_reason = Column(Text, nullable=False)
    reviewed_by_recruiter = Column(Boolean, default=False)

    application = relationship("JobApplication", back_populates="discrepancy_flags")


class CandidateIdVerification(Base):
    __tablename__ = "candidate_id_verification"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), unique=True, nullable=False)

    live_photo_path = Column(Text, nullable=False) # Base64 data URL in PostgreSQL
    government_id_path = Column(Text, nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow)
    verification_status = Column(String(50), default="pending") # pending, verified, flagged

    application = relationship("JobApplication", back_populates="id_verification")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    status = Column(String(50), default="scheduled") # scheduled, preflight, in_progress, paused, completed, cancelled
    current_phase = Column(String(50), default="greeting") # greeting, self_intro, deep_dive, closing, completed
    total_questions_planned = Column(Integer, default=5)
    duration_planned_mins = Column(Integer, default=20)
    gemini_model_used = Column(String(100), default="gemini-3.5-flash")
    system_prompt_snapshot = Column(Text, nullable=True)
    interviewer_brief = Column(Text, nullable=True)
    running_summary = Column(Text, nullable=True)

    current_question_index = Column(Integer, default=0)
    follow_up_count_in_current = Column(Integer, default=0)
    speech_speed = Column(Float, default=1.05)
    captions_enabled = Column(Boolean, default=True)
    is_practice = Column(Boolean, default=False)
    recording_consent = Column(Boolean, default=False)
    recording_retention_days = Column(Integer, default=0, nullable=True)

    blueprint_id = Column(String(36), ForeignKey("interview_blueprints.id", ondelete="SET NULL"), nullable=True)
    blueprint_version = Column(Integer, nullable=True)
    runtime_state = Column(JSON, default=dict) # Section index, active probes, anchor_alt used, etc.

    started_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    application = relationship("JobApplication", back_populates="interview_sessions")
    job = relationship("JobPosting")
    blueprint = relationship("InterviewBlueprint", foreign_keys=[blueprint_id])
    questions = relationship("InterviewQuestion", back_populates="session", cascade="all, delete-orphan", order_by="InterviewQuestion.question_index")
    evaluations = relationship("InterviewEvaluation", back_populates="session", cascade="all, delete-orphan", lazy="selectin")
    transcript_turns = relationship("InterviewTranscriptTurn", back_populates="session", cascade="all, delete-orphan", order_by="InterviewTranscriptTurn.sequence_number", lazy="selectin")
    integrity_events = relationship("InterviewIntegrityEvent", back_populates="session", cascade="all, delete-orphan", lazy="selectin")
    feedback_entries = relationship("InterviewFeedback", back_populates="session", cascade="all, delete-orphan", lazy="selectin")
    expectation_coverages = relationship("SessionExpectationCoverage", back_populates="session", cascade="all, delete-orphan", lazy="selectin")


class InterviewGenerationRun(Base):
    __tablename__ = "interview_generation_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    model_name = Column(String(100), nullable=False)
    prompt_template_version = Column(String(50), nullable=False)
    input_snapshot_hash = Column(String(64), nullable=False, index=True)
    resume_version_used = Column(String(64), nullable=True)
    job_rubric_version_used = Column(String(64), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    failure_reason = Column(Text, nullable=True)
    gemini_request_id = Column(String(255), nullable=True)
    token_usage_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    application = relationship("JobApplication", back_populates="generation_runs")
    questions = relationship("InterviewQuestion", back_populates="generation_run")


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    generation_run_id = Column(String(36), ForeignKey("interview_generation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    skill_id = Column(String(36), ForeignKey("job_skills.id", ondelete="SET NULL"), nullable=True)
    question_index = Column(Integer, nullable=False)

    skill_name = Column(String(200), nullable=True)
    skill_category = Column(String(100), nullable=True)
    priority_tier = Column(String(10), nullable=True) # P0, P1, P2

    question_text = Column(Text, nullable=False)
    expected_key_points = Column(JSON, default=list) # Rubric anchors from job rubrics
    follow_up_depth_allowed = Column(Integer, default=2)
    follow_up_count = Column(Integer, default=0)

    question_state = Column(String(30), default="queued") # queued, asked, candidate_turn, evaluating, follow_up, completed, not_assessed, skipped
    coverage_status = Column(JSON, default=dict) # {key_point: "covered" | "uncovered"}
    evidence_turn_ids = Column(JSON, default=list) # [turn_id, ...]
    approved_by_recruiter = Column(Boolean, default=False)

    section_id = Column(String(36), ForeignKey("blueprint_sections.id", ondelete="SET NULL"), nullable=True)
    blueprint_question_id = Column(String(36), ForeignKey("blueprint_questions.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(50), nullable=True) # anchor, escalation, probe, intro_hook, candidate_qa, closing
    personalization_context = Column(JSON, nullable=True)
    target_expectation_ids = Column(JSON, default=list)

    candidate_answer_transcript = Column(Text, nullable=True)
    superseded_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="questions")
    generation_run = relationship("InterviewGenerationRun", back_populates="questions")
    section = relationship("BlueprintSection")
    blueprint_question = relationship("BlueprintQuestion")


class InterviewTranscriptTurn(Base):
    __tablename__ = "interview_transcript_turns"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(String(36), ForeignKey("interview_questions.id", ondelete="SET NULL"), nullable=True)
    turn_type = Column(String(30), nullable=False)
    speaker = Column(String(20), nullable=False)
    text = Column(Text, nullable=False)
    spoken_text = Column(Text, nullable=True)
    was_interrupted = Column(Boolean, default=False, nullable=False)
    audio_ref = Column(String(1000), nullable=True)
    stt_confidence = Column(Float, nullable=True)
    stt_final_ms = Column(Float, nullable=True)
    llm_ttft_ms = Column(Float, nullable=True)
    tts_first_audio_ms = Column(Float, nullable=True)
    total_response_ms = Column(Float, nullable=True)
    provider = Column(String(50), nullable=True) # gemini, tokenharbor
    model_name = Column(String(100), nullable=True)
    sequence_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="transcript_turns")
    question = relationship("InterviewQuestion")


class InterviewEvaluation(Base):
    __tablename__ = "interview_evaluations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    overall_score = Column(Float, nullable=True)
    verdict = Column(String(30), nullable=True)
    insufficient_evidence = Column(Boolean, default=False, nullable=False)
    p0_not_assessed_skills = Column(JSON, default=list)
    second_pass_triggered = Column(Boolean, default=False, nullable=False)
    summary = Column(Text, nullable=True)
    strengths = Column(JSON, default=list)
    concerns = Column(JSON, default=list)
    candidate_summary = Column(Text, nullable=True)
    model_name = Column(String(100), nullable=False, default="gemini-3.5-flash")
    prompt_version = Column(String(50), nullable=False, default="v1")
    token_usage_json = Column(JSON, nullable=True)
    raw_response_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    session = relationship("InterviewSession", back_populates="evaluations")
    application = relationship("JobApplication")
    job = relationship("JobPosting")
    skill_scores = relationship("InterviewSkillScore", back_populates="evaluation", cascade="all, delete-orphan", lazy="selectin")


class InterviewSkillScore(Base):
    __tablename__ = "interview_skill_scores"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_id = Column(String(36), ForeignKey("interview_evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id = Column(String(36), nullable=True)
    skill_name = Column(String(255), nullable=False)
    priority_tier = Column(String(10), nullable=False, default="P0")
    weight_percentage = Column(Float, nullable=False, default=0.0)
    level = Column(String(20), nullable=False, default="NOT_ASSESSED")
    numeric_score = Column(Float, nullable=True)
    rationale = Column(Text, nullable=True)
    evidence_json = Column(JSON, default=list)
    verified_quote_count = Column(Integer, default=0, nullable=False)
    unverified_quote_count = Column(Integer, default=0, nullable=False)
    low_confidence_warning = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    evaluation = relationship("InterviewEvaluation", back_populates="skill_scores")


class InterviewIntegrityEvent(Base):
    __tablename__ = "interview_integrity_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="low")
    policy_tier = Column(String(30), nullable=False, default="Moderate")
    details_json = Column(JSON, default=dict)
    turn_id = Column(String(36), ForeignKey("interview_transcript_turns.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="integrity_events")
    application = relationship("JobApplication")


class InterviewFeedback(Base):
    __tablename__ = "interview_feedback"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=True, index=True)
    candidate_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="feedback_entries")
    application = relationship("JobApplication")


class WebSocketTicketUse(Base):
    """Single-use consumption record for short-lived WebSocket tickets.

    The ticket id is a unique primary key, so concurrent replays race on a
    database constraint rather than on process-local memory. This makes replay
    protection effective across multiple server workers.
    """

    __tablename__ = "websocket_ticket_uses"

    ticket_id = Column(String(64), primary_key=True)
    session_id = Column(String(128), nullable=False, index=True)
    user_id = Column(String(128), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_role = Column(String(30), nullable=True)
    event_type = Column(String(100), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="success")
    job_id = Column(String(36), nullable=True, index=True)
    application_id = Column(String(36), nullable=True, index=True)
    session_id = Column(String(36), nullable=True, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CandidatePersonalization(Base):
    __tablename__ = "candidate_personalizations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    blueprint_id = Column(String(36), ForeignKey("interview_blueprints.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, default="completed") # pending, completed, failed
    input_hash = Column(String(64), nullable=True, index=True)
    intro_hook = Column(Text, nullable=False)
    deep_dive_project = Column(JSON, default=dict) # {"project_name": "...", "claims_to_verify": ["..."]}
    per_skill_probes = Column(JSON, default=list) # [{"section_id": "...", "skill_name": "...", "probe_text": "...", "rationale": "..."}] or {"<skill_id>": "probe text"}
    claims_to_verify = Column(JSON, default=list) # ["..."]
    raw_model_response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    application = relationship("JobApplication", back_populates="personalization")
    blueprint = relationship("InterviewBlueprint")


class SessionExpectationCoverage(Base):
    __tablename__ = "session_expectation_coverage"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    expectation_id = Column(String(36), ForeignKey("blueprint_expectations.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(30), default="not_probed", nullable=False) # not_probed, partial, covered
    evidence_turn_ids = Column(JSON, default=list)
    evidence_quote = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="expectation_coverages")
    expectation = relationship("BlueprintExpectation", back_populates="coverages")



