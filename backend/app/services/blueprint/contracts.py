"""Pydantic contracts and schemas for Job Interview Blueprint."""

from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import List, Optional, Dict, Any
from datetime import datetime


class ExpectationDraft(BaseModel):
    expectation_text: str = Field(..., description="Concrete technical/behavioral expectation")
    source_rubric_level: Optional[str] = Field("L4", description="Source level from rubric: L3, L4, or L5")
    importance: str = Field("core", description="'core' or 'stretch'")


class QuestionDraft(BaseModel):
    question_role: str = Field(..., description="'anchor', 'anchor_alt', 'escalation', or 'probe'")
    question_text: str = Field(..., description="Spoken question text, max 35-45 words, 1 question mark")
    trigger_condition: Optional[str] = Field(None, description="Condition to ask this question (probes)")
    target_expectation_indices: List[int] = Field(default_factory=list, description="Indices of expectations targeted")


class SkillSectionContent(BaseModel):
    skill_name: str
    expectations: List[ExpectationDraft] = Field(..., min_length=2, max_length=5)
    anchor_question: QuestionDraft
    anchor_alt_question: Optional[QuestionDraft] = Field(None, description="Hypothetical version when candidate lacks direct experience")
    escalation_question: QuestionDraft
    probes: List[QuestionDraft] = Field(..., min_length=3, max_length=6)


class ValidationIssue(BaseModel):
    severity: str = Field("error", description="'error' or 'warning'")
    section_index: Optional[int] = None
    skill_name: Optional[str] = None
    field: str
    message: str


class ValidationReport(BaseModel):
    is_valid: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    issues: List[ValidationIssue] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    review_provider: Optional[str] = None
    review_model: Optional[str] = None


# API response models
class BlueprintExpectationOut(BaseModel):
    id: str
    order_index: int
    expectation_text: str
    source_rubric_level: Optional[str] = None
    importance: str = "core"

    model_config = ConfigDict(from_attributes=True)


class BlueprintQuestionOut(BaseModel):
    id: str
    order_index: int
    question_role: str
    question_text: str
    trigger_condition: Optional[str] = None
    target_expectation_ids: List[str] = []
    word_count: int = 0
    source: str = "llm"

    model_config = ConfigDict(from_attributes=True)


class BlueprintSectionOut(BaseModel):
    id: str
    order_index: int
    section_type: str
    title: str
    skill_id: Optional[str] = None
    skill_name: Optional[str] = None
    priority_tier: Optional[str] = None
    allocated_minutes: float
    target_rubric_tier: Optional[str] = None
    welcome_script: Optional[str] = None
    closing_script: Optional[str] = None
    expectations: List[BlueprintExpectationOut] = []
    questions: List[BlueprintQuestionOut] = []

    model_config = ConfigDict(from_attributes=True)


class InterviewBlueprintOut(BaseModel):
    id: str
    job_id: str
    version: int
    status: str
    total_duration_mins: int
    active_skill_mins: float
    fixed_overhead_mins: float
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    validation_report: Optional[Dict[str, Any]] = None
    input_hash: Optional[str] = None
    is_stale: bool = False
    generation_provider: Optional[str] = None
    generation_model: Optional[str] = None
    generation_latency_ms: Optional[float] = None
    generation_stages_ms: Optional[Dict[str, Any]] = None
    is_generated_with_backup: bool = False
    backup_badge: Optional[str] = None
    can_be_approved: bool = True
    created_at: datetime
    updated_at: datetime
    sections: List[BlueprintSectionOut] = []

    model_config = ConfigDict(from_attributes=True)


class BlueprintApprovalRequest(BaseModel):
    blueprint_id: str
    confirmed_warnings: bool = False
    notes: Optional[str] = None


class SuggestSkillsRequest(BaseModel):
    job_title: str
    department: Optional[str] = "Engineering"
    seniority_level: Optional[str] = "Mid-Level (L4)"
    job_description: Optional[str] = ""
    interview_duration_mins: Optional[int] = 20


class BlueprintUpdatePayload(BaseModel):
    sections: List[Dict[str, Any]]


class SuggestedSkill(BaseModel):
    name: str
    category: str = "Core Technical"
    priority_tier: str = "P1"
    weight_percentage: int = 25
    rubric_l1: str = ""
    rubric_l2: str = ""
    rubric_l3: str = ""
    rubric_l4: str = ""
    rubric_l5: str = ""


class SuggestedSkillsResponse(BaseModel):
    skills: List[SuggestedSkill]


class LLMReviewItem(BaseModel):
    section_index: Optional[int] = None
    skill_name: Optional[str] = None
    target_item: Optional[str] = None
    issue_type: str = "relevance"  # "relevance", "escalation_containment", "technique_leakage", "seniority_fit", "voice_suitability"
    severity: str = "error"  # "error" | "warning"
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            reason_val = (
                data.get("reason")
                or data.get("description")
                or data.get("message")
                or data.get("explanation")
                or data.get("detail")
                or data.get("rationale")
                or ""
            )
            data["reason"] = str(reason_val)
            if "severity" in data:
                data["severity"] = "warning" if "warning" in str(data["severity"]).lower() else "error"
        return data


class BatchedBlueprintReviewResponse(BaseModel):
    is_approved: bool = True
    summary: str = "Blueprint review passed"
    issues: List[LLMReviewItem] = Field(default_factory=list)
    review_provider: Optional[str] = "gemini"
    review_model: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_response(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If model returned "reviews" or "feedback" or "findings" instead of "issues"
            if "issues" not in data:
                data["issues"] = data.get("findings") or data.get("reviews") or data.get("feedback") or []
        return data



