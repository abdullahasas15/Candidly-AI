import re
import logging
from typing import List

from .contracts import GeneratedInterviewPlan, QuestionGenerationSnapshot

logger = logging.getLogger(__name__)


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def validate_plan(
    plan: GeneratedInterviewPlan, snapshot: QuestionGenerationSnapshot
) -> List[str]:
    errors = []
    known_skills = {c.skill_id: c for c in snapshot.competencies}
    known_names = {_normalized(c.name): c for c in snapshot.competencies}
    custom_ids = {q.id for q in snapshot.custom_questions}
    expected_count = sum(c.allocated_questions for c in snapshot.competencies)

    if len(plan.questions) != expected_count:
        logger.warning(
            "Generated question count %s does not match budget %s for application %s",
            len(plan.questions),
            expected_count,
            snapshot.application_id,
        )

    seen = set()
    p0_seen = set()
    hidden_text = [
        anchor
        for competency in snapshot.competencies
        for anchor in competency.rubrics.values()
        if anchor
    ] + [point for q in snapshot.custom_questions for point in q.expected_key_points]

    for question in plan.questions:
        if question.skill_id not in known_skills and not any(
            ref == f"custom_question:{custom_id}" for custom_id in custom_ids for ref in question.source_refs
        ):
            errors.append(f"Question {question.question_index} does not map to a known skill or custom question")
        if question.skill_id in known_skills:
            p0_seen.add(question.skill_id) if known_skills[question.skill_id].priority == "P0" else None
        text = _normalized(question.question_text)
        if text in seen:
            errors.append(f"Duplicate question at index {question.question_index}")
        seen.add(text)
        for hidden in hidden_text:
            if len(_normalized(hidden)) >= 20 and _normalized(hidden) in text:
                errors.append(f"Hidden rubric/key-point text leaked at index {question.question_index}")
                break
        if question.follow_up_depth_allowed > snapshot.job.max_followup_depth:
            errors.append(f"Question {question.question_index} exceeds follow-up policy")

    required_p0 = {c.skill_id for c in snapshot.competencies if c.priority == "P0" and c.allocated_questions > 0}
    missing = required_p0 - p0_seen
    if missing:
        errors.append(f"Missing P0 questions for skills: {', '.join(sorted(missing))}")
    return errors
