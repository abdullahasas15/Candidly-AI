import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models import (
    JobPosting,
    JobSkill,
    InterviewBlueprint,
    BlueprintSection,
    BlueprintExpectation,
    BlueprintQuestion,
    SessionExpectationCoverage,
)
from backend.app.services.blueprint.generator import generate_job_blueprint, generate_single_skill_section
from backend.app.services.blueprint.contracts import SkillSectionContent
from backend.app.services.blueprint.validator import validate_blueprint

logger = logging.getLogger(__name__)


def compute_job_input_hash(job: JobPosting) -> str:
    """Compute deterministic SHA-256 hash of job criteria affecting blueprint."""
    skills_repr = []
    for s in sorted(job.skills or [], key=lambda x: (x.priority_tier or "", x.name or "")):
        skills_repr.append({
            "name": (s.name or "").strip().lower(),
            "priority_tier": s.priority_tier,
            "weight_percentage": float(s.weight_percentage or 0),
            "target_level_min": getattr(s, "target_level_min", None),
            "target_level_max": getattr(s, "target_level_max", None),
            "rubric_l1": (s.rubric_l1 or "").strip(),
            "rubric_l2": (s.rubric_l2 or "").strip(),
            "rubric_l3": (s.rubric_l3 or "").strip(),
            "rubric_l4": (s.rubric_l4 or "").strip(),
            "rubric_l5": (s.rubric_l5 or "").strip(),
        })

    payload = {
        "title": (job.job_title or "").strip().lower(),
        "role_key": getattr(job, "role_key", "custom"),
        "role_template_version": getattr(job, "role_template_version", None),
        "seniority_level": (job.seniority_level or "").strip().lower(),
        "interview_duration_mins": job.interview_duration_mins or 20,
        "max_followup_depth": job.max_followup_depth or 1,
        "pacing_strictness": (job.pacing_strictness or "").strip().lower(),
        "interviewer_tone": (job.interviewer_tone or "").strip().lower(),
        "skills": skills_repr,
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_job_blueprint(
    db: AsyncSession,
    job_id: str,
    version: Optional[int] = None,
) -> Optional[InterviewBlueprint]:
    """Retrieve active, latest, or versioned blueprint for a job with all relations."""
    stmt = (
        select(InterviewBlueprint)
        .where(InterviewBlueprint.job_id == job_id)
        .options(
            selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.expectations),
            selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.questions),
        )
    )

    if version is not None:
        stmt = stmt.where(InterviewBlueprint.version == version)
        result = await db.execute(stmt)
        return result.scalars().first()

    # Check if job has an active blueprint
    job_stmt = select(JobPosting.active_blueprint_id).where(JobPosting.id == job_id)
    job_res = await db.execute(job_stmt)
    active_bp_id = job_res.scalar_one_or_none()

    if active_bp_id:
        active_stmt = stmt.where(InterviewBlueprint.id == active_bp_id)
        result = await db.execute(active_stmt)
        bp = result.scalars().first()
        if bp:
            return bp

    # Fallback to latest version
    stmt = stmt.order_by(InterviewBlueprint.version.desc())
    result = await db.execute(stmt)
    return result.scalars().first()


async def list_job_blueprint_versions(
    db: AsyncSession,
    job_id: str,
) -> List[InterviewBlueprint]:
    """List all versioned blueprints for a job."""
    stmt = (
        select(InterviewBlueprint)
        .where(InterviewBlueprint.job_id == job_id)
        .order_by(InterviewBlueprint.version.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def save_job_blueprint(
    db: AsyncSession,
    blueprint_data: Dict[str, Any],
    auto_approve: bool = False,
    approved_by_id: Optional[str] = None,
) -> InterviewBlueprint:
    """Persist generated blueprint dictionary into relational models."""
    job_id = blueprint_data["job_id"]

    # Fetch job to compute input_hash
    job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
    job_res = await db.execute(job_stmt)
    job = job_res.scalars().first()
    inp_hash = compute_job_input_hash(job) if job else None

    # Determine next version
    ver_stmt = select(func.coalesce(func.max(InterviewBlueprint.version), 0)).where(
        InterviewBlueprint.job_id == job_id
    )
    res = await db.execute(ver_stmt)
    next_ver = res.scalar_one() + 1

    val_rep = blueprint_data.get("validation_report")
    has_errors = bool(val_rep and val_rep.get("errors"))
    status_val = "approved" if (auto_approve and not has_errors) else "draft"
    approved_at_val = datetime.utcnow() if (auto_approve and not has_errors) else None

    blueprint = InterviewBlueprint(
        job_id=job_id,
        version=next_ver,
        status=status_val,
        total_duration_mins=blueprint_data["total_duration_mins"],
        active_skill_mins=blueprint_data["active_skill_mins"],
        fixed_overhead_mins=blueprint_data["fixed_overhead_mins"],
        approved_by=approved_by_id if (auto_approve and not has_errors) else None,
        approved_at=approved_at_val,
        validation_report=blueprint_data.get("validation_report"),
        input_hash=inp_hash,
        is_stale=False,
        generation_provider=blueprint_data.get("generation_provider"),
        generation_model=blueprint_data.get("generation_model"),
        generation_latency_ms=blueprint_data.get("generation_latency_ms"),
        generation_stages_ms=blueprint_data.get("generation_stages_ms"),
        is_generated_with_backup=bool(blueprint_data.get("is_generated_with_backup", False)),
    )
    db.add(blueprint)
    await db.flush()

    for s_idx, sec_dict in enumerate(blueprint_data.get("sections", [])):
        section = BlueprintSection(
            blueprint_id=blueprint.id,
            order_index=sec_dict.get("order_index", s_idx),
            section_type=sec_dict["section_type"],
            title=sec_dict["title"],
            skill_id=sec_dict.get("skill_id"),
            skill_name=sec_dict.get("skill_name"),
            priority_tier=sec_dict.get("priority_tier"),
            allocated_minutes=sec_dict["allocated_minutes"],
            target_rubric_tier=sec_dict.get("target_rubric_tier"),
            welcome_script=sec_dict.get("welcome_script"),
            closing_script=sec_dict.get("closing_script"),
        )
        db.add(section)
        await db.flush()

        content = sec_dict.get("content")
        if isinstance(content, dict):
            content = SkillSectionContent.model_validate(content)

        if content and isinstance(content, SkillSectionContent):
            # Save expectations
            exp_id_map: Dict[int, str] = {}
            for e_idx, exp_draft in enumerate(content.expectations):
                expectation = BlueprintExpectation(
                    section_id=section.id,
                    order_index=e_idx,
                    expectation_text=exp_draft.expectation_text,
                    source_rubric_level=exp_draft.source_rubric_level,
                    importance=exp_draft.importance,
                )
                db.add(expectation)
                await db.flush()
                exp_id_map[e_idx] = expectation.id

            q_order = 0
            # Anchor
            anchor_text = content.anchor_question.question_text
            anchor_q = BlueprintQuestion(
                section_id=section.id,
                order_index=q_order,
                question_role="anchor",
                question_text=anchor_text,
                word_count=len(anchor_text.strip().split()),
                target_expectation_ids=list(exp_id_map.values()),
                source="llm",
            )
            db.add(anchor_q)
            q_order += 1

            # Anchor Alt (Hypothetical)
            if getattr(content, "anchor_alt_question", None) and content.anchor_alt_question.question_text:
                alt_text = content.anchor_alt_question.question_text
                alt_q = BlueprintQuestion(
                    section_id=section.id,
                    order_index=q_order,
                    question_role="anchor_alt",
                    question_text=alt_text,
                    word_count=len(alt_text.strip().split()),
                    target_expectation_ids=list(exp_id_map.values()),
                    source="llm",
                )
                db.add(alt_q)
                q_order += 1

            # Escalation
            esc_text = content.escalation_question.question_text
            esc_q = BlueprintQuestion(
                section_id=section.id,
                order_index=q_order,
                question_role="escalation",
                question_text=esc_text,
                word_count=len(esc_text.strip().split()),
                target_expectation_ids=list(exp_id_map.values()),
                source="llm",
            )
            db.add(esc_q)
            q_order += 1

            # Probes
            for probe_draft in content.probes:
                probe_text = probe_draft.question_text
                target_ids = [
                    exp_id_map[i] for i in probe_draft.target_expectation_indices
                    if i in exp_id_map
                ]
                probe_q = BlueprintQuestion(
                    section_id=section.id,
                    order_index=q_order,
                    question_role="probe",
                    question_text=probe_text,
                    trigger_condition=probe_draft.trigger_condition,
                    word_count=len(probe_text.strip().split()),
                    target_expectation_ids=target_ids,
                    source="llm",
                )
                db.add(probe_q)
                q_order += 1
        elif sec_dict.get("expectations") or sec_dict.get("questions"):
            exp_id_map = {}
            for e_idx, e_data in enumerate(sec_dict.get("expectations", [])):
                expectation = BlueprintExpectation(
                    section_id=section.id,
                    order_index=e_data.get("order_index", e_idx),
                    expectation_text=e_data.get("expectation_text", ""),
                    source_rubric_level=e_data.get("source_rubric_level", "L4"),
                    importance=e_data.get("importance", "core"),
                )
                db.add(expectation)
                await db.flush()
                exp_id_map[e_idx] = expectation.id

            for q_idx, q_data in enumerate(sec_dict.get("questions", [])):
                q_text = q_data.get("question_text", "")
                q = BlueprintQuestion(
                    section_id=section.id,
                    order_index=q_data.get("order_index", q_idx),
                    question_role=q_data.get("question_role", "probe"),
                    question_text=q_text,
                    trigger_condition=q_data.get("trigger_condition"),
                    target_expectation_ids=q_data.get("target_expectation_ids", list(exp_id_map.values())),
                    word_count=q_data.get("word_count", len(q_text.strip().split())),
                    source=q_data.get("source", "llm"),
                )
                db.add(q)
                await db.flush()

    if auto_approve and not has_errors:
        await db.execute(
            update(JobPosting)
            .where(JobPosting.id == job_id)
            .values(active_blueprint_id=blueprint.id)
        )

    await db.commit()

    # Re-fetch with full relationships
    return await get_job_blueprint(db, job_id, next_ver)  # type: ignore[return-value]


async def update_or_fork_job_blueprint(
    db: AsyncSession,
    job_id: str,
    blueprint_id: str,
    updated_sections: List[Dict[str, Any]],
    user_id: str,
) -> InterviewBlueprint:
    """
    Update a blueprint.
    Copy-on-write: if blueprint is currently 'approved', creates a new draft version.
    Never mutates an approved blueprint.
    Re-runs validator and stores updated validation report.
    """
    orig_bp = await get_job_blueprint(db, job_id)
    if not orig_bp or orig_bp.id != blueprint_id:
        bp_stmt = (
            select(InterviewBlueprint)
            .where(InterviewBlueprint.id == blueprint_id)
            .options(
                selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.expectations),
                selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.questions),
            )
        )
        res = await db.execute(bp_stmt)
        orig_bp = res.scalars().first()

    if not orig_bp:
        raise ValueError(f"Blueprint {blueprint_id} not found")

    job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
    job_res = await db.execute(job_stmt)
    job = job_res.scalars().first()
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job_skills_data = [
        {"id": s.id, "name": s.name, "priority_tier": s.priority_tier, "weight_percentage": s.weight_percentage}
        for s in (job.skills or [])
    ]

    # Validate updated sections
    report = validate_blueprint(
        sections=updated_sections,
        job_skills=job_skills_data,
        active_skill_time=orig_bp.active_skill_mins,
        total_duration_mins=orig_bp.total_duration_mins,
        seniority_level=job.seniority_level or "mid",
    )

    inp_hash = compute_job_input_hash(job)

    if orig_bp.status == "approved":
        # COPY-ON-WRITE: create new draft version
        ver_stmt = select(func.coalesce(func.max(InterviewBlueprint.version), 0)).where(
            InterviewBlueprint.job_id == job_id
        )
        ver_res = await db.execute(ver_stmt)
        next_ver = ver_res.scalar_one() + 1

        target_bp = InterviewBlueprint(
            job_id=job_id,
            version=next_ver,
            status="draft",
            total_duration_mins=orig_bp.total_duration_mins,
            active_skill_mins=orig_bp.active_skill_mins,
            fixed_overhead_mins=orig_bp.fixed_overhead_mins,
            approved_by=None,
            approved_at=None,
            validation_report=report.model_dump(),
            input_hash=inp_hash,
            is_stale=False,
        )
        db.add(target_bp)
        await db.flush()
    else:
        # Mutate draft in-place
        target_bp = orig_bp
        target_bp.validation_report = report.model_dump()
        target_bp.input_hash = inp_hash
        target_bp.is_stale = False
        target_bp.updated_at = datetime.utcnow()

        # Delete existing sections to re-populate
        for s in list(target_bp.sections):
            await db.delete(s)
        await db.flush()

    # Populate sections, expectations, and questions
    for s_idx, s_data in enumerate(updated_sections):
        sec = BlueprintSection(
            blueprint_id=target_bp.id,
            order_index=s_idx,
            section_type=s_data.get("section_type", "skill"),
            title=s_data.get("title", f"Section {s_idx + 1}"),
            skill_id=s_data.get("skill_id"),
            skill_name=s_data.get("skill_name"),
            priority_tier=s_data.get("priority_tier"),
            allocated_minutes=float(s_data.get("allocated_minutes", 4.0)),
            target_rubric_tier=s_data.get("target_rubric_tier"),
            welcome_script=s_data.get("welcome_script"),
            closing_script=s_data.get("closing_script"),
        )
        db.add(sec)
        await db.flush()

        # Expectations
        exp_id_map: Dict[int, str] = {}
        for e_idx, e_data in enumerate(s_data.get("expectations", [])):
            exp = BlueprintExpectation(
                section_id=sec.id,
                order_index=e_idx,
                expectation_text=e_data.get("expectation_text", ""),
                source_rubric_level=e_data.get("source_rubric_level", "L4"),
                importance=e_data.get("importance", "core"),
            )
            db.add(exp)
            await db.flush()
            exp_id_map[e_idx] = exp.id

        # Questions
        for q_idx, q_data in enumerate(s_data.get("questions", [])):
            q_text = q_data.get("question_text", "")
            q = BlueprintQuestion(
                section_id=sec.id,
                order_index=q_idx,
                question_role=q_data.get("question_role", "probe"),
                question_text=q_text,
                trigger_condition=q_data.get("trigger_condition"),
                target_expectation_ids=q_data.get("target_expectation_ids", []),
                word_count=len(q_text.strip().split()),
                source=q_data.get("source", "llm"),
            )
            db.add(q)
            await db.flush()

    await db.commit()
    return await get_job_blueprint(db, job_id, target_bp.version)  # type: ignore[return-value]


async def regenerate_blueprint_section(
    db: AsyncSession,
    job_id: str,
    blueprint_id: str,
    section_id: str,
    user_id: str,
) -> InterviewBlueprint:
    """Regenerate a single skill section using LLM and update/fork the blueprint."""
    bp = await get_job_blueprint(db, job_id)
    if not bp or bp.id != blueprint_id:
        bp_stmt = (
            select(InterviewBlueprint)
            .where(InterviewBlueprint.id == blueprint_id)
            .options(
                selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.expectations),
                selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.questions),
            )
        )
        res = await db.execute(bp_stmt)
        bp = res.scalars().first()

    if not bp:
        raise ValueError(f"Blueprint {blueprint_id} not found")

    job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
    job_res = await db.execute(job_stmt)
    job = job_res.scalars().first()
    if not job:
        raise ValueError(f"Job {job_id} not found")

    # Find the target section
    target_sec = next((s for s in bp.sections if s.id == section_id), None)
    if not target_sec:
        raise ValueError(f"Section {section_id} not found in blueprint")

    # Find corresponding skill
    skill_info = next((s for s in (job.skills or []) if s.id == target_sec.skill_id or s.name == target_sec.skill_name), None)
    skill_dict = {
        "id": skill_info.id if skill_info else None,
        "name": target_sec.skill_name,
        "priority_tier": target_sec.priority_tier or "P1",
        "allocated_minutes": target_sec.allocated_minutes,
        "recommended_expectations": 4,
    }

    # Generate fresh section content
    gen_result = await generate_single_skill_section(
        job_title=job.job_title,
        seniority_level=job.seniority_level or "Mid-Level (L4)",
        skill_info=skill_dict,
        section_index=target_sec.order_index,
    )
    new_content: SkillSectionContent = gen_result["content"]

    # Serialize current blueprint to dicts
    serialized = serialize_blueprint(bp, current_job=job)
    for s in serialized["sections"]:
        if s["id"] == section_id:
            s["expectations"] = [
                {
                    "expectation_text": e.expectation_text,
                    "source_rubric_level": e.source_rubric_level,
                    "importance": e.importance,
                }
                for e in new_content.expectations
            ]
            q_list = [
                {
                    "question_role": "anchor",
                    "question_text": new_content.anchor_question.question_text,
                    "target_expectation_ids": [],
                    "source": "llm",
                },
                {
                    "question_role": "escalation",
                    "question_text": new_content.escalation_question.question_text,
                    "target_expectation_ids": [],
                    "source": "llm",
                },
            ]
            for p in new_content.probes:
                q_list.append({
                    "question_role": "probe",
                    "question_text": p.question_text,
                    "trigger_condition": p.trigger_condition,
                    "target_expectation_ids": [],
                    "source": "llm",
                })
            s["questions"] = q_list
            break

    # Update or fork
    return await update_or_fork_job_blueprint(
        db=db,
        job_id=job_id,
        blueprint_id=blueprint_id,
        updated_sections=serialized["sections"],
        user_id=user_id,
    )


async def approve_job_blueprint(
    db: AsyncSession,
    job_id: str,
    blueprint_id: str,
    user_id: str,
    confirmed_warnings: bool = False,
) -> InterviewBlueprint:
    """Approve a blueprint version, enforcing validation gates, and make it active for the job."""
    bp = await get_job_blueprint(db, job_id)
    if not bp or bp.id != blueprint_id:
        bp_stmt = (
            select(InterviewBlueprint)
            .where(InterviewBlueprint.id == blueprint_id)
            .options(
                selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.expectations),
                selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.questions),
            )
        )
        res = await db.execute(bp_stmt)
        bp = res.scalars().first()

    if not bp:
        raise ValueError(f"Blueprint {blueprint_id} not found")

    job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
    job_res = await db.execute(job_stmt)
    job = job_res.scalars().first()
    if not job:
        raise ValueError(f"Job {job_id} not found")

    # Re-run validation on the blueprint before approval
    serialized = serialize_blueprint(bp, current_job=job)
    job_skills_data = [
        {"id": s.id, "name": s.name, "priority_tier": s.priority_tier, "weight_percentage": s.weight_percentage}
        for s in (job.skills or [])
    ]
    report = validate_blueprint(
        sections=serialized["sections"],
        job_skills=job_skills_data,
        active_skill_time=bp.active_skill_mins,
        total_duration_mins=bp.total_duration_mins,
        seniority_level=job.seniority_level or "mid",
    )

    # Check newly computed errors as well as any existing stored validation errors
    existing_errors = list((bp.validation_report or {}).get("errors") or [])
    all_errors = list(dict.fromkeys(report.errors + existing_errors))

    if bp.is_generated_with_backup and all_errors:
        raise ValueError("Blueprint generated with backup provider has unresolved errors ('generated with backup; regenerate on primary') and cannot be approved.")

    if all_errors:
        raise ValueError(f"Approval blocked due to validation errors: {'; '.join(all_errors)}")

    if report.warnings and not confirmed_warnings:
        raise ValueError(f"Blueprint has validation warnings that must be confirmed: {'; '.join(report.warnings)}")

    inp_hash = compute_job_input_hash(job)

    await db.execute(
        update(InterviewBlueprint)
        .where(InterviewBlueprint.id == blueprint_id)
        .values(
            status="approved",
            approved_by=user_id,
            approved_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            validation_report=report.model_dump(),
            input_hash=inp_hash,
            is_stale=False,
        )
    )

    await db.execute(
        update(JobPosting)
        .where(JobPosting.id == job_id)
        .values(active_blueprint_id=blueprint_id)
    )

    await db.commit()

    active_bp = await get_job_blueprint(db, job_id)
    if not active_bp:
        raise ValueError(f"Blueprint {blueprint_id} not found after approval")
    return active_bp


async def ensure_job_blueprint(
    db: AsyncSession,
    job_id: str,
) -> InterviewBlueprint:
    """Ensure a job has an active approved blueprint."""
    existing = await get_job_blueprint(db, job_id)
    if existing:
        return existing

    # Fetch job with skills
    job_stmt = (
        select(JobPosting)
        .where(JobPosting.id == job_id)
        .options(selectinload(JobPosting.skills))
    )
    res = await db.execute(job_stmt)
    job = res.scalars().first()
    if not job:
        raise ValueError(f"Job {job_id} not found")

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

    blueprint_data = await generate_job_blueprint(
        job_id=job.id,
        job_title=job.job_title,
        seniority_level=job.seniority_level or "mid",
        duration_mins=job.interview_duration_mins or 20,
        skills=skills_data,
        job_description=job.job_description or "",
    )

    return await save_job_blueprint(
        db=db,
        blueprint_data=blueprint_data,
        auto_approve=True,
    )


def serialize_blueprint(bp: InterviewBlueprint, current_job: Optional[JobPosting] = None) -> Dict[str, Any]:
    """Serialize an InterviewBlueprint model into a JSON-safe dictionary matching InterviewBlueprintOut."""
    is_stale_val = bool(bp.is_stale)
    if current_job and bp.input_hash:
        curr_hash = compute_job_input_hash(current_job)
        if bp.input_hash != curr_hash:
            is_stale_val = True

    return {
        "id": bp.id,
        "job_id": bp.job_id,
        "version": bp.version,
        "status": bp.status,
        "total_duration_mins": bp.total_duration_mins,
        "active_skill_mins": bp.active_skill_mins,
        "fixed_overhead_mins": bp.fixed_overhead_mins,
        "approved_by": bp.approved_by,
        "approved_at": bp.approved_at,
        "validation_report": bp.validation_report,
        "input_hash": bp.input_hash,
        "is_stale": is_stale_val,
        "generation_provider": getattr(bp, "generation_provider", None),
        "generation_model": getattr(bp, "generation_model", None),
        "generation_latency_ms": getattr(bp, "generation_latency_ms", None),
        "generation_stages_ms": getattr(bp, "generation_stages_ms", None),
        "is_generated_with_backup": bool(getattr(bp, "is_generated_with_backup", False)),
        "backup_badge": (
            "generated with backup; regenerate on primary"
            if bool(getattr(bp, "is_generated_with_backup", False)) and bool((bp.validation_report or {}).get("errors"))
            else ("generated with backup provider" if bool(getattr(bp, "is_generated_with_backup", False)) else None)
        ),
        "can_be_approved": not (
            bool((bp.validation_report or {}).get("errors"))
        ),
        "created_at": bp.created_at,
        "updated_at": bp.updated_at,
        "sections": [
            {
                "id": s.id,
                "order_index": s.order_index,
                "section_type": s.section_type,
                "title": s.title,
                "skill_id": s.skill_id,
                "skill_name": s.skill_name,
                "priority_tier": s.priority_tier,
                "allocated_minutes": s.allocated_minutes,
                "target_rubric_tier": s.target_rubric_tier,
                "welcome_script": s.welcome_script,
                "closing_script": s.closing_script,
                "expectations": [
                    {
                        "id": e.id,
                        "order_index": e.order_index,
                        "expectation_text": e.expectation_text,
                        "source_rubric_level": e.source_rubric_level,
                        "importance": e.importance,
                    }
                    for e in (s.expectations or [])
                ],
                "questions": [
                    {
                        "id": q.id,
                        "order_index": q.order_index,
                        "question_role": q.question_role,
                        "question_text": q.question_text,
                        "trigger_condition": q.trigger_condition,
                        "target_expectation_ids": q.target_expectation_ids or [],
                        "word_count": q.word_count,
                        "source": getattr(q, "source", "llm") or "llm",
                    }
                    for q in (s.questions or [])
                ],
            }
            for s in (bp.sections or [])
        ],
    }


async def init_session_expectation_coverage(
    db: AsyncSession,
    session_id: str,
    blueprint_id: str,
) -> List[SessionExpectationCoverage]:
    """Initialize session_expectation_coverage rows for all expectations in the blueprint."""
    # Query all expectations in this blueprint
    stmt = (
        select(BlueprintExpectation)
        .join(BlueprintSection, BlueprintExpectation.section_id == BlueprintSection.id)
        .where(BlueprintSection.blueprint_id == blueprint_id)
        .order_by(BlueprintSection.order_index, BlueprintExpectation.order_index)
    )
    res = await db.execute(stmt)
    expectations = res.scalars().all()

    coverage_rows: List[SessionExpectationCoverage] = []
    for exp in expectations:
        cov = SessionExpectationCoverage(
            session_id=session_id,
            expectation_id=exp.id,
            status="not_probed",
            evidence_turn_ids=[],
        )
        db.add(cov)
        coverage_rows.append(cov)

    if coverage_rows:
        await db.commit()
    return coverage_rows


async def record_expectation_coverage(
    db: AsyncSession,
    session_id: str,
    expectation_id: str,
    status_val: str,
    turn_id: Optional[str] = None,
) -> Optional[SessionExpectationCoverage]:
    """Update status ('not_probed', 'partial', 'covered') and record evidence turn."""
    stmt = (
        select(SessionExpectationCoverage)
        .where(
            SessionExpectationCoverage.session_id == session_id,
            SessionExpectationCoverage.expectation_id == expectation_id,
        )
    )
    res = await db.execute(stmt)
    cov = res.scalars().first()
    if not cov:
        # If record does not exist yet, create it on demand
        cov = SessionExpectationCoverage(
            session_id=session_id,
            expectation_id=expectation_id,
            status=status_val,
            evidence_turn_ids=[turn_id] if turn_id else [],
        )
        db.add(cov)
    else:
        cov.status = status_val
        cov.updated_at = datetime.utcnow()
        if turn_id:
            turns = list(cov.evidence_turn_ids or [])
            if turn_id not in turns:
                turns.append(turn_id)
                cov.evidence_turn_ids = turns

    await db.commit()
    return cov


async def get_session_expectation_coverage(
    db: AsyncSession,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Retrieve full expectation coverage progress with expectation details for a session."""
    stmt = (
        select(SessionExpectationCoverage, BlueprintExpectation, BlueprintSection)
        .join(BlueprintExpectation, SessionExpectationCoverage.expectation_id == BlueprintExpectation.id)
        .join(BlueprintSection, BlueprintExpectation.section_id == BlueprintSection.id)
        .where(SessionExpectationCoverage.session_id == session_id)
        .order_by(BlueprintSection.order_index, BlueprintExpectation.order_index)
    )
    res = await db.execute(stmt)
    results = []
    for cov, exp, sec in res.all():
        results.append({
            "id": cov.id,
            "session_id": cov.session_id,
            "expectation_id": cov.expectation_id,
            "status": cov.status,
            "evidence_turn_ids": cov.evidence_turn_ids or [],
            "updated_at": cov.updated_at,
            "expectation_text": exp.expectation_text,
            "source_rubric_level": exp.source_rubric_level,
            "importance": exp.importance,
            "skill_name": sec.skill_name,
            "priority_tier": sec.priority_tier,
            "section_title": sec.title,
        })
    return results


