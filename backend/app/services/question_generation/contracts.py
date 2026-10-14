from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JobSnapshot(BaseModel):
    id: str
    title: str
    department: str
    description: str
    seniority: str
    duration_minutes: int
    max_followup_depth: int
    requirements: Dict[str, Any] = {}


class CompetencySnapshot(BaseModel):
    skill_id: str
    name: str
    category: str
    priority: str
    weight_percentage: float
    rubrics: Dict[str, Optional[str]] = {}
    allocated_questions: int = 0
    time_allocation_minutes: float = 0.0
    target_rubric_tier: str = ""


class CandidateSnapshot(BaseModel):
    application_id: str
    fit_pitch: Optional[str] = None
    self_reported_experience_years: float = 0.0
    resume_structured_data: Dict[str, Any] = {}
    discrepancy_flags: List[Dict[str, Any]] = []
    resume_id: Optional[str] = None
    resume_sha256: Optional[str] = None
    resume_mime_type: Optional[str] = None


class CustomQuestionSnapshot(BaseModel):
    id: str
    question_text: str
    category: str
    difficulty_level: str
    expected_key_points: List[str] = []
    priority_tier: str
    question_type: str
    is_required: bool
    options: List[str] = []


class QuestionGenerationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "question-generation.v1"
    application_id: str
    job: JobSnapshot
    competencies: List[CompetencySnapshot] = []
    certifications: List[Dict[str, Any]] = []
    candidate: CandidateSnapshot
    custom_questions: List[CustomQuestionSnapshot] = []
    input_snapshot_hash: Optional[str] = None


class GeneratedQuestion(BaseModel):
    question_index: int = Field(ge=0)
    skill_id: Optional[str] = None
    skill_name: Optional[str] = None
    skill_category: Optional[str] = None
    priority_tier: Optional[str] = None
    question_type: str = "technical_deep_dive"
    question_text: str = Field(min_length=1)
    expected_key_points: List[str] = []
    follow_up_depth_allowed: int = Field(default=0, ge=0)
    source_refs: List[str] = []


class GenerationMetadata(BaseModel):
    model: str
    generated_at: str
    input_snapshot_hash: str


class GeneratedInterviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "generated-interview-plan.v1"
    generation_metadata: GenerationMetadata
    questions: List[GeneratedQuestion] = []


class ProviderResult(BaseModel):
    plan: GeneratedInterviewPlan
    request_id: Optional[str] = None
    token_usage: Dict[str, Any] = {}
    retry_count: int = 0
