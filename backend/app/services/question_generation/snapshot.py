import hashlib
import json
from typing import Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models import JobApplication, JobPosting

from .contracts import (
    CandidateSnapshot,
    CompetencySnapshot,
    CustomQuestionSnapshot,
    JobSnapshot,
    QuestionGenerationSnapshot,
)


def _hash_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


async def build_snapshot(
    application_id: str, db: AsyncSession
) -> Tuple[QuestionGenerationSnapshot, JobApplication]:
    stmt = (
        select(JobApplication)
        .where(JobApplication.id == application_id)
        .options(
            selectinload(JobApplication.job).selectinload(JobPosting.skills),
            selectinload(JobApplication.job).selectinload(JobPosting.certifications),
            selectinload(JobApplication.job).selectinload(JobPosting.custom_questions),
            selectinload(JobApplication.job).selectinload(JobPosting.question_plans),
            selectinload(JobApplication.resume),
            selectinload(JobApplication.discrepancy_flags),
        )
    )
    result = await db.execute(stmt)
    application = result.scalars().first()
    if not application or not application.job:
        raise ValueError("Application or target job not found")
    if not application.resume:
        raise ValueError("A parsed resume is required before question generation")
    if application.resume.file_type.lower() != "pdf":
        raise ValueError("Question generation requires a PDF resume for Gemini native multimodal input")
    if not application.resume.file_data:
        raise ValueError("Resume PDF bytes are missing")

    job = application.job
    plan_by_name = {p.skill_name.casefold(): p for p in (job.question_plans or [])}
    competencies = []
    for skill in job.skills or []:
        plan = plan_by_name.get(skill.name.casefold())
        competencies.append(
            CompetencySnapshot(
                skill_id=skill.id,
                name=skill.name,
                category=skill.category or "Core Technical",
                priority=skill.priority_tier or "P1",
                weight_percentage=skill.weight_percentage,
                rubrics={
                    "l1": skill.rubric_l1,
                    "l2": skill.rubric_l2,
                    "l3": skill.rubric_l3,
                    "l4": skill.rubric_l4,
                    "l5": skill.rubric_l5,
                },
                allocated_questions=plan.allocated_questions if plan else 0,
                time_allocation_minutes=plan.time_allocation_minutes if plan else 0,
                target_rubric_tier=plan.target_rubric_tier if plan else "",
            )
        )

    resume_hash = hashlib.sha256(application.resume.file_data).hexdigest()
    snapshot = QuestionGenerationSnapshot(
        application_id=application.id,
        job=JobSnapshot(
            id=job.id,
            title=job.job_title,
            department=job.department,
            description=job.job_description or "",
            seniority=job.seniority_level,
            duration_minutes=job.interview_duration_mins,
            max_followup_depth=job.max_followup_depth,
            requirements={
                "min_degree_level": job.min_degree_level,
                "degree_enforcement_type": job.degree_enforcement_type,
                "accepted_majors": job.accepted_majors or [],
                "min_cgpa": job.min_cgpa,
                "total_experience_years": job.total_experience_years,
                "domain_experience_years": job.domain_experience_years,
                "leadership_required": job.leadership_required,
            },
        ),
        competencies=competencies,
        certifications=[
            {
                "id": c.id,
                "name": c.name,
                "issuing_org": c.issuing_org,
                "priority_tier": c.priority_tier,
                "verification_required": c.verification_required,
            }
            for c in (job.certifications or [])
        ],
        candidate=CandidateSnapshot(
            application_id=application.id,
            fit_pitch=application.fit_pitch,
            self_reported_experience_years=application.self_reported_experience_years or 0,
            resume_structured_data=application.resume.parsed_structured_data or {},
            discrepancy_flags=[
                {
                    "field_name": flag.field_name,
                    "candidate_stated_value": flag.candidate_stated_value,
                    "resume_derived_value": flag.resume_derived_value,
                    "flag_reason": flag.flag_reason,
                }
                for flag in (application.discrepancy_flags or [])
            ],
            resume_id=application.resume.id,
            resume_sha256=resume_hash,
            resume_mime_type="application/pdf",
        ),
        custom_questions=[
            CustomQuestionSnapshot(
                id=q.id,
                question_text=q.question_text,
                category=q.category or "Core Technical",
                difficulty_level=q.difficulty_level or "Mid-Senior",
                expected_key_points=q.expected_key_points or [],
                priority_tier=q.priority_tier or "P0",
                question_type=q.question_type or "text",
                is_required=q.is_required,
                options=q.options or [],
            )
            for q in (job.custom_questions or [])
        ],
    )
    normalized = snapshot.model_dump(exclude={"input_snapshot_hash"})
    snapshot.input_snapshot_hash = _hash_json(normalized)
    return snapshot, application
