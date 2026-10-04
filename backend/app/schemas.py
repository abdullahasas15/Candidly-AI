from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Any, Dict
from datetime import datetime

class SkillCreate(BaseModel):
    name: str
    category: str = "Core Technical"
    priority_tier: str = "P0" # P0, P1, P2
    weight_percentage: float = Field(..., ge=1.0, le=100.0)
    rubric_l1: Optional[str] = None
    rubric_l2: Optional[str] = None
    rubric_l3: Optional[str] = None
    rubric_l4: Optional[str] = None
    rubric_l5: Optional[str] = None

class SkillResponse(BaseModel):
    id: str
    job_id: str
    name: str
    category: str
    priority_tier: str
    weight_percentage: float
    rubric_l1: Optional[str] = None
    rubric_l2: Optional[str] = None
    rubric_l3: Optional[str] = None
    rubric_l4: Optional[str] = None
    rubric_l5: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class CertificationCreate(BaseModel):
    name: str
    issuing_org: str
    priority_tier: str = "P1" # P0, P1, P2
    verification_required: bool = False

class CertificationResponse(BaseModel):
    id: str
    job_id: str
    name: str
    issuing_org: str
    priority_tier: str
    verification_required: bool

    model_config = ConfigDict(from_attributes=True)

class CustomQuestionCreate(BaseModel):
    question_text: str
    category: str = "Core Technical"
    difficulty_level: str = "Mid-Senior"
    expected_key_points: List[str] = []
    priority_tier: str = "P0"
    question_type: str = "text" # text, textarea, yes_no, single_choice
    is_required: bool = True
    options: List[str] = []

class CustomQuestionResponse(BaseModel):
    id: str
    job_id: str
    question_text: str
    category: str
    difficulty_level: str
    expected_key_points: List[str] = []
    priority_tier: str
    question_type: str = "text"
    is_required: bool = True
    options: List[str] = []

    model_config = ConfigDict(from_attributes=True)

class QuestionPlanResponse(BaseModel):
    id: Optional[str] = None
    job_id: Optional[str] = None
    skill_name: str
    skill_priority: str
    allocated_questions: int
    time_allocation_minutes: float
    weight_percentage: float
    target_rubric_tier: str

    model_config = ConfigDict(from_attributes=True)

class JobCreate(BaseModel):
    # Role Identity & Metadata
    job_title: str
    department: str
    job_description: str = "N/A"
    seniority_level: str = "Mid-Level (L4)"
    employment_type: str = "Full-Time"
    workplace_model: str = "Remote"
    permitted_locations: List[str] = ["Global Remote", "United States", "India"]

    # Educational & Academic
    min_degree_level: str = "Bachelor's Degree (B.S. / B.E. / B.Tech)"
    degree_enforcement_type: str = "Equivalent Professional Experience Allowed"
    accepted_majors: List[str] = ["Computer Science", "Software Engineering", "Information Technology"]
    min_cgpa: str = "3.0 / 4.0"
    cgpa_strict_filter: bool = False
    grad_year_start: Optional[int] = None
    grad_year_end: Optional[int] = None

    # Professional Experience
    total_experience_years: float = 3.0
    domain_experience_years: float = 2.0
    leadership_required: bool = False

    # Interviewer Policy & Pacing
    interview_duration_mins: int = 20
    allow_grace_extension: bool = True
    max_followup_depth: int = 1
    pacing_strictness: str = "Balanced"
    interviewer_tone: str = "Direct, technical, tech-lead caliber; probes for architectural trade-offs; warm but concise."
    integrity_policy_tier: str = "Moderate"

    # Compensation & Location Budget
    salary_range_min: Optional[float] = None
    salary_range_max: Optional[float] = None
    salary_currency: str = "USD"

    # Associated Arrays
    skills: List[SkillCreate] = []
    certifications: List[CertificationCreate] = []
    custom_questions: List[CustomQuestionCreate] = []

    @field_validator("skills")
    @classmethod
    def validate_weights(cls, skills: List[SkillCreate]):
        if not skills:
            return skills
        total_weight = sum(s.weight_percentage for s in skills)
        if round(total_weight, 1) != 100.0:
            raise ValueError(f"Total skill weights must sum to exactly 100%. Current sum: {total_weight}%")
        return skills

class JobResponse(BaseModel):
    id: str
    job_title: str
    department: str
    job_description: str = "N/A"
    seniority_level: str
    employment_type: str
    workplace_model: str
    permitted_locations: List[str]
    min_degree_level: str
    degree_enforcement_type: str
    accepted_majors: List[str]
    min_cgpa: str
    cgpa_strict_filter: bool
    grad_year_start: Optional[int] = None
    grad_year_end: Optional[int] = None
    total_experience_years: float
    domain_experience_years: float
    leadership_required: bool
    interview_duration_mins: int
    allow_grace_extension: bool
    max_followup_depth: int
    pacing_strictness: str
    interviewer_tone: str
    integrity_policy_tier: str
    salary_range_min: Optional[float] = None
    salary_range_max: Optional[float] = None
    salary_currency: Optional[str] = "USD"
    recruiter_id: Optional[str] = None
    status: str
    created_at: datetime
    skills: List[SkillResponse] = []
    certifications: List[CertificationResponse] = []
    custom_questions: List[CustomQuestionResponse] = []
    question_plans: List[QuestionPlanResponse] = []

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    full_name: str
    role: str = "recruiter" # 'recruiter' or 'candidate'
    company_name: Optional[str] = None
    headline: Optional[str] = None

class UserLogin(BaseModel):
    email: str
    password: str
    role: Optional[str] = None

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    company_name: Optional[str] = None
    headline: Optional[str] = None
    avatar_url: Optional[str] = None
    auth_provider: Optional[str] = "local"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class CandidateApplicationResponse(BaseModel):
    id: str
    user_id: str
    job_id: str
    status: str
    fit_score: Optional[float] = None
    applied_at: datetime
    job: Optional[JobResponse] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# Candidate Application Flow Schemas
# ---------------------------------------------------------

class WorkExperienceEntry(BaseModel):
    company: str
    role: str
    start_date: str
    end_date: str
    duration_years: float = 0.0
    description: Optional[str] = None
    highlights: List[str] = []
    technologies: List[str] = []

class EducationEntry(BaseModel):
    degree: str
    institution: str
    field: Optional[str] = None
    graduation_year: Optional[int] = None
    gpa: Optional[str] = None
    honors: Optional[str] = None

class CertificationEntry(BaseModel):
    name: str
    issuing_org: Optional[str] = None
    issue_year: Optional[int] = None
    credential_id: Optional[str] = None
    url: Optional[str] = None

class ProjectEntry(BaseModel):
    title: str
    role: Optional[str] = None
    technologies: List[str] = []
    description: Optional[str] = None
    url: Optional[str] = None

class StructuredResumeData(BaseModel):
    summary: Optional[str] = None
    work_experience: List[WorkExperienceEntry] = []
    education: List[EducationEntry] = []
    certifications: List[CertificationEntry] = []
    projects: List[ProjectEntry] = []
    skills: List[str] = []
    skills_by_category: Dict[str, List[str]] = {}
    contact_info: Dict[str, Optional[str]] = {}
    total_experience_years: float = 0.0

class CandidateResumeResponse(BaseModel):
    id: str
    application_id: str
    original_file_path: Optional[str] = None
    original_file_name: str
    file_type: str
    file_size_bytes: int
    file_base64: Optional[str] = None
    parsed_text: Optional[str] = None
    parsed_structured_data: Dict[str, Any] = {}
    ocr_used: bool = False
    parsing_status: str = "pending"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ResumeDiscrepancyFlagResponse(BaseModel):
    id: str
    application_id: str
    field_name: str
    candidate_stated_value: Optional[str] = None
    resume_derived_value: Optional[str] = None
    flag_reason: str
    reviewed_by_recruiter: bool = False

    model_config = ConfigDict(from_attributes=True)

class CandidateIdVerificationResponse(BaseModel):
    id: str
    application_id: str
    live_photo_path: str
    government_id_path: Optional[str] = None
    captured_at: datetime
    verification_status: str = "pending"

    model_config = ConfigDict(from_attributes=True)

class JobApplicationCreate(BaseModel):
    job_id: str
    candidate_id: Optional[str] = None
    full_name: str
    email: str
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    self_reported_experience_years: float = 0.0
    fit_pitch: Optional[str] = None
    expected_salary: Optional[float] = None
    expected_salary_currency: str = "USD"
    screening_answers: List[Dict[str, Any]] = []
    work_authorization: Optional[str] = "Authorized"
    visa_sponsorship_needed: bool = False

class JobApplicationUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    self_reported_experience_years: Optional[float] = None
    fit_pitch: Optional[str] = None
    expected_salary: Optional[float] = None
    expected_salary_currency: Optional[str] = None
    status: Optional[str] = None
    screening_answers: Optional[List[Dict[str, Any]]] = None
    work_authorization: Optional[str] = None
    visa_sponsorship_needed: Optional[bool] = None

class JobApplicationResponse(BaseModel):
    id: str
    job_id: str
    candidate_id: Optional[str] = None
    full_name: str
    email: str
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    status: str
    applied_at: datetime
    self_reported_experience_years: float
    fit_pitch: Optional[str] = None
    expected_salary: Optional[float] = None
    expected_salary_currency: str
    screening_answers: List[Dict[str, Any]] = []
    work_authorization: Optional[str] = "Authorized"
    visa_sponsorship_needed: bool = False
    created_at: datetime
    updated_at: datetime

    job: Optional[JobResponse] = None
    resume: Optional[CandidateResumeResponse] = None
    discrepancy_flags: List[ResumeDiscrepancyFlagResponse] = []
    id_verification: Optional[CandidateIdVerificationResponse] = None

    model_config = ConfigDict(from_attributes=True)

class JobApplicationListItem(BaseModel):
    id: str
    job_id: str
    candidate_id: Optional[str] = None
    full_name: str
    email: str
    status: str
    applied_at: datetime
    self_reported_experience_years: float
    resume_experience_years: Optional[float] = None
    expected_salary: Optional[float] = None
    expected_salary_currency: Optional[str] = "USD"
    discrepancy_count: int = 0
    unresolved_discrepancies: int = 0

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# Interview Preparation & Session Execution Schemas
# ---------------------------------------------------------

class InterviewQuestionCreate(BaseModel):
    session_id: str
    question_index: int
    skill_name: Optional[str] = None
    skill_category: Optional[str] = None
    priority_tier: Optional[str] = "P0"
    question_text: str
    expected_key_points: List[str] = []
    follow_up_depth_allowed: int = 2

class InterviewQuestionResponse(BaseModel):
    id: str
    session_id: str
    question_index: int
    skill_name: Optional[str] = None
    skill_category: Optional[str] = None
    priority_tier: Optional[str] = None
    question_text: str
    expected_key_points: List[str] = []
    follow_up_depth_allowed: int = 2
    follow_up_count: int = 0
    candidate_answer_transcript: Optional[str] = None
    evaluation_score: Optional[float] = None
    evaluation_feedback: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class InterviewSessionCreate(BaseModel):
    application_id: str
    job_id: str
    total_questions_planned: int = 5
    duration_planned_mins: int = 20
    gemini_model_used: str = "gemini-2.5-flash"
    system_prompt_snapshot: Optional[str] = None

class InterviewSessionResponse(BaseModel):
    id: str
    application_id: str
    job_id: str
    status: str
    total_questions_planned: int
    duration_planned_mins: int
    gemini_model_used: str
    system_prompt_snapshot: Optional[str] = None
    current_question_index: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    questions: List[InterviewQuestionResponse] = []

    model_config = ConfigDict(from_attributes=True)



