"""Job Interview Blueprint service package."""

from backend.app.services.blueprint.contracts import (
    ExpectationDraft,
    QuestionDraft,
    SkillSectionContent,
    ValidationReport,
    ValidationIssue,
    InterviewBlueprintOut,
    BlueprintSectionOut,
    BlueprintExpectationOut,
    BlueprintQuestionOut,
)
from backend.app.services.blueprint.validator import validate_blueprint
from backend.app.services.blueprint.generator import (
    generate_job_blueprint,
    generate_single_skill_section,
    suggest_skills_from_jd,
    BlueprintGenerationError,
)
from backend.app.services.blueprint.persistence import (
    get_job_blueprint,
    save_job_blueprint,
    approve_job_blueprint,
    ensure_job_blueprint,
    serialize_blueprint,
    list_job_blueprint_versions,
    init_session_expectation_coverage,
    record_expectation_coverage,
    get_session_expectation_coverage,
    compute_job_input_hash,
    update_or_fork_job_blueprint,
    regenerate_blueprint_section,
)

__all__ = [
    "ExpectationDraft",
    "QuestionDraft",
    "SkillSectionContent",
    "ValidationReport",
    "ValidationIssue",
    "InterviewBlueprintOut",
    "BlueprintSectionOut",
    "BlueprintExpectationOut",
    "BlueprintQuestionOut",
    "validate_blueprint",
    "generate_job_blueprint",
    "BlueprintGenerationError",
    "get_job_blueprint",
    "save_job_blueprint",
    "approve_job_blueprint",
    "ensure_job_blueprint",
    "serialize_blueprint",
    "init_session_expectation_coverage",
    "record_expectation_coverage",
    "get_session_expectation_coverage",
]
