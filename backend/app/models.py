import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from backend.app.database import Base

class JobPosting(Base):
    __tablename__ = "job_postings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # 1. Role Identity & Metadata Fields
    job_title = Column(String(150), nullable=False)
    department = Column(String(100), nullable=False)
    seniority_level = Column(String(50), nullable=False, default="Mid-Level (L4)") # Intern, Entry-Level (L3), Mid-Level (L4), Senior (L5), Lead
    employment_type = Column(String(50), nullable=False, default="Full-Time") # Full-Time, Part-Time, Contract, Internship
    workplace_model = Column(String(50), nullable=False, default="Remote") # Remote, Hybrid, On-site
    permitted_locations = Column(JSON, default=list) # e.g. ["United States", "Canada", "Remote (EST/PST)"]
    
    # 2. Educational & Academic Qualification Metrics
    min_degree_level = Column(String(100), default="Bachelor's Degree (B.S. / B.E. / B.Tech)")
    degree_enforcement_type = Column(String(100), default="Equivalent Professional Experience Allowed")
    accepted_majors = Column(JSON, default=lambda: ["Computer Science", "Software Engineering", "Information Technology"])
    min_cgpa = Column(String(50), default="3.0 / 4.0")
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
    pacing_strictness = Column(String(50), default="Balanced") # Relaxed, Balanced, Aggressive
    interviewer_tone = Column(Text, default="Direct, technical, tech-lead caliber; probes for architectural trade-offs; warm but concise.")
    integrity_policy_tier = Column(String(50), default="Moderate") # Basic, Moderate, Strict

    # 5. Compensation & Location Budget
    salary_range_min = Column(Float, nullable=True)
    salary_range_max = Column(Float, nullable=True)
    salary_currency = Column(String(10), default="USD")

    recruiter_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active") # active, draft, archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    recruiter = relationship("User", back_populates="posted_jobs", lazy="selectin")
    skills = relationship("JobSkill", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    certifications = relationship("JobCertification", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    custom_questions = relationship("JobCustomQuestion", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    question_plans = relationship("JobQuestionPlan", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    applications = relationship("JobApplication", back_populates="job", cascade="all, delete-orphan", lazy="selectin")
    interview_sessions = relationship("InterviewSession", back_populates="job", cascade="all, delete-orphan", lazy="selectin")



class JobSkill(Base):
    __tablename__ = "job_skills"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(100), nullable=False)
    category = Column(String(100), default="Core Technical") # Core Technical, Tooling, Architecture, Soft & Cultural
    priority_tier = Column(String(20), default="P0") # P0 Mandatory, P1 High, P2 Bonus
    weight_percentage = Column(Float, nullable=False) # e.g. 35.0

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

    job = relationship("JobPosting", back_populates="custom_questions")


class JobQuestionPlan(Base):
    __tablename__ = "job_question_plans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    skill_name = Column(String(100), nullable=False)
    skill_priority = Column(String(20), default="P0")
    allocated_questions = Column(Integer, nullable=False)
    time_allocation_minutes = Column(Float, nullable=False)
    weight_percentage = Column(Float, nullable=False)
    target_rubric_tier = Column(String(50), default="L3-L4")

    job = relationship("JobPosting", back_populates="question_plans")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False) # Production: email/password authentication
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="recruiter") # 'recruiter' or 'candidate'
    company_name = Column(String(150), nullable=True) # for recruiters
    headline = Column(String(200), nullable=True) # for candidates
    avatar_url = Column(String(500), nullable=True)
    auth_provider = Column(String(50), default="local") # 'local'
    created_at = Column(DateTime, default=datetime.utcnow)

    posted_jobs = relationship("JobPosting", back_populates="recruiter", lazy="selectin")
    applications = relationship("CandidateApplication", back_populates="user", cascade="all, delete-orphan", lazy="selectin")
    job_applications = relationship("JobApplication", back_populates="candidate", cascade="all, delete-orphan", lazy="selectin")



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

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job = relationship("JobPosting", back_populates="applications", lazy="selectin")
    candidate = relationship("User", back_populates="job_applications", lazy="selectin")
    resume = relationship("CandidateResume", back_populates="application", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    discrepancy_flags = relationship("ResumeDiscrepancyFlag", back_populates="application", cascade="all, delete-orphan", lazy="selectin")
    id_verification = relationship("CandidateIdVerification", back_populates="application", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    interview_sessions = relationship("InterviewSession", back_populates="application", cascade="all, delete-orphan", lazy="selectin")


class CandidateResume(Base):
    __tablename__ = "candidate_resumes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False)

    original_file_path = Column(String(500), nullable=False)
    original_file_name = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False) # pdf, docx, txt
    file_size_bytes = Column(Integer, nullable=False)

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

    live_photo_path = Column(String(500), nullable=False)
    government_id_path = Column(String(500), nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow)
    verification_status = Column(String(50), default="pending") # pending, verified, flagged

    application = relationship("JobApplication", back_populates="id_verification")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)

    status = Column(String(50), default="scheduled") # scheduled, in_progress, completed, abandoned
    total_questions_planned = Column(Integer, default=8)
    total_questions_asked = Column(Integer, default=0)
    duration_planned_mins = Column(Integer, default=20)
    actual_duration_secs = Column(Integer, default=0)

    gemini_model_used = Column(String(100), default="gemini-2.5-flash")
    system_prompt_snapshot = Column(Text, nullable=True) # Frozen copy of prompt used

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    application = relationship("JobApplication", back_populates="interview_sessions", lazy="selectin")
    job = relationship("JobPosting", back_populates="interview_sessions", lazy="selectin")
    questions = relationship("InterviewQuestion", back_populates="session", cascade="all, delete-orphan", order_by="InterviewQuestion.question_index", lazy="selectin")


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)

    question_index = Column(Integer, nullable=False, default=1)
    skill_name = Column(String(150), nullable=True)
    skill_category = Column(String(100), nullable=True)
    priority_tier = Column(String(20), default="P0") # P0, P1, P2

    question_text = Column(Text, nullable=False)
    expected_key_points = Column(JSON, default=list) # Array of key points expected in answer

    candidate_answer = Column(Text, nullable=True)
    follow_up_question = Column(Text, nullable=True)
    follow_up_answer = Column(Text, nullable=True)

    time_spent_secs = Column(Integer, default=0)
    rubric_level_assessed = Column(String(20), nullable=True) # e.g. L1, L2, L3, L4, L5
    evaluation_notes = Column(Text, nullable=True)

    asked_at = Column(DateTime, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("InterviewSession", back_populates="questions")




