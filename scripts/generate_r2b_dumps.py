#!/usr/bin/env python3
"""Generates R2b deliverables:
1. Re-creates SDE Entry job from template (without vague 'projects' skill) and outputs full blueprint dump.
2. Creates AI Engineer Mid job from template and outputs full blueprint dump.
3. Generates 4x3 matrix summary table (4 templates x 3 seniority levels: entry, mid, senior).
"""

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal
from backend.app.models import JobPosting, JobSkill, JobCertification, InterviewBlueprint
from backend.app.services.role_templates import (
    load_role_templates,
    get_all_role_templates,
    get_role_template_by_key,
    extract_template_skills_for_seniority,
)
from backend.app.services.blueprint.generator import generate_job_blueprint
from backend.app.services.blueprint.persistence import (
    save_job_blueprint,
    get_job_blueprint,
    serialize_blueprint,
    compute_job_input_hash,
)
from backend.app.services.blueprint.validator import validate_blueprint
from scripts.dump_blueprint import format_blueprint_markdown


async def create_job_from_template(session, role_key: str, seniority: str, duration_mins: int = 20) -> JobPosting:
    tpl = await get_role_template_by_key(session, role_key)
    if not tpl:
        raise ValueError(f"Role template '{role_key}' not found")

    skills_data = extract_template_skills_for_seniority(tpl, seniority)

    job = JobPosting(
        role_key=tpl.role_key,
        role_template_id=tpl.id,
        role_template_version=tpl.version,
        job_title=f"{tpl.display_name} ({seniority.capitalize()})",
        department="Engineering",
        job_description=tpl.description,
        seniority_level=seniority,
        employment_type="Full-Time",
        workplace_model="Remote",
        permitted_locations=["Global Remote", "United States", "India"],
        interview_duration_mins=duration_mins,
        allow_grace_extension=True,
        max_followup_depth=1,
        pacing_strictness=tpl.default_pacing or "Balanced",
        interviewer_tone=tpl.default_interviewer_tone or "Direct, technical tech-lead; probes for trade-offs.",
        integrity_policy_tier="Moderate",
        salary_range_min=120000,
        salary_range_max=160000,
        salary_currency="USD",
        status="active",
    )
    session.add(job)
    await session.flush()

    for s in skills_data:
        skill = JobSkill(
            job_id=job.id,
            name=s["name"],
            category=s["category"],
            priority_tier=s["priority_tier"],
            weight_percentage=s["weight_percentage"],
            template_skill_key=s.get("template_skill_key"),
            target_level_min=s.get("target_level_min"),
            target_level_max=s.get("target_level_max"),
            source="template",
            rubric_l1=s.get("rubric_l1"),
            rubric_l2=s.get("rubric_l2"),
            rubric_l3=s.get("rubric_l3"),
            rubric_l4=s.get("rubric_l4"),
            rubric_l5=s.get("rubric_l5"),
        )
        session.add(skill)

    await session.commit()
    await session.refresh(job)
    return job


async def run_pipeline():
    print("Loading Role Templates...")
    async with AsyncSessionLocal() as session:
        await load_role_templates(session)

    dump_path_sde = ROOT_DIR / "docs" / "DUMP_SDE_ENTRY.md"
    if dump_path_sde.exists():
        print(f"✓ SDE Entry Blueprint already exists at: {dump_path_sde}")
    else:
        # 1. Re-create SDE Entry Job
        print("\n--- 1. Creating Clean SDE Entry Job ---")
        async with AsyncSessionLocal() as session:
            sde_job = await create_job_from_template(session, "sde", "entry", duration_mins=20)
            print(f"Created SDE Job: ID={sde_job.id}, Title='{sde_job.job_title}', Skills={len(sde_job.skills)}")

            skills_payload = [
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
                for s in sde_job.skills
            ]

            print("Generating Blueprint for SDE Entry...")
            sde_bp_data = await generate_job_blueprint(
                job_id=sde_job.id,
                job_title=sde_job.job_title,
                seniority_level="entry",
                duration_mins=20,
                skills=skills_payload,
                job_description=sde_job.job_description,
            )
            sde_bp = await save_job_blueprint(session, sde_bp_data, auto_approve=True)
            sde_serialized = serialize_blueprint(sde_bp, current_job=sde_job)
            sde_val = validate_blueprint(
                sections=sde_serialized.get("sections", []),
                job_skills=skills_payload,
                active_skill_time=sde_bp.active_skill_mins,
                total_duration_mins=sde_bp.total_duration_mins,
                seniority_level="entry",
            )
            sde_md = format_blueprint_markdown(sde_job, sde_bp, sde_serialized, sde_val)
            dump_path_sde.write_text(sde_md, encoding="utf-8")
            print(f"✓ SDE Entry Blueprint saved to: {dump_path_sde}")
            print(f"  Valid: {sde_val.is_valid}, Errors: {len(sde_val.errors)}, Warnings: {len(sde_val.warnings)}")

    dump_path_ai = ROOT_DIR / "docs" / "DUMP_AI_ENGINEER_MID.md"
    if dump_path_ai.exists():
        print(f"✓ AI Engineer Mid Blueprint already exists at: {dump_path_ai}")
    else:
        # 2. Create AI Engineer Mid Job
        print("\n--- 2. Creating AI Engineer Mid Job ---")
        async with AsyncSessionLocal() as session:
            ai_job = await create_job_from_template(session, "ai_engineer", "mid", duration_mins=30)
            print(f"Created AI Engineer Job: ID={ai_job.id}, Title='{ai_job.job_title}', Skills={len(ai_job.skills)}")

            skills_payload = [
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
                for s in ai_job.skills
            ]

            print("Generating Blueprint for AI Engineer Mid...")
            ai_bp_data = await generate_job_blueprint(
                job_id=ai_job.id,
                job_title=ai_job.job_title,
                seniority_level="mid",
                duration_mins=30,
                skills=skills_payload,
                job_description=ai_job.job_description,
            )
            ai_bp = await save_job_blueprint(session, ai_bp_data, auto_approve=True)
            ai_serialized = serialize_blueprint(ai_bp, current_job=ai_job)
            ai_val = validate_blueprint(
                sections=ai_serialized.get("sections", []),
                job_skills=skills_payload,
                active_skill_time=ai_bp.active_skill_mins,
                total_duration_mins=ai_bp.total_duration_mins,
                seniority_level="mid",
            )
            ai_md = format_blueprint_markdown(ai_job, ai_bp, ai_serialized, ai_val)
            dump_path_ai.write_text(ai_md, encoding="utf-8")
            print(f"✓ AI Engineer Mid Blueprint saved to: {dump_path_ai}")
            print(f"  Valid: {ai_val.is_valid}, Errors: {len(ai_val.errors)}, Warnings: {len(ai_val.warnings)}")

    # 3. 4x3 Matrix Summary Table (4 templates x 3 seniorities)
    print("\n--- 3. Generating 4x3 Matrix Validator Summary ---")
    roles = ["sde", "ai_engineer", "devops", "data_engineer"]
    seniorities = ["entry", "mid", "senior"]

    import json
    matrix_cache_path = ROOT_DIR / "docs" / "matrix_cache.json"
    cache = {}
    if matrix_cache_path.exists():
        try:
            cache = json.loads(matrix_cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    matrix_rows = []

    async with AsyncSessionLocal() as session:
        all_tpls = {t.role_key: t for t in await get_all_role_templates(session)}

        for r_key in roles:
            tpl = all_tpls[r_key]
            for sen in seniorities:
                cache_key = f"{r_key}_{sen}"
                t0 = time.time()
                skills_data = extract_template_skills_for_seniority(tpl, sen)
                skills_payload = [
                    {
                        "id": f"temp_{i}",
                        "name": s["name"],
                        "category": s["category"],
                        "priority_tier": s["priority_tier"],
                        "weight_percentage": s["weight_percentage"],
                        "rubric_l1": s.get("rubric_l1"),
                        "rubric_l2": s.get("rubric_l2"),
                        "rubric_l3": s.get("rubric_l3"),
                        "rubric_l4": s.get("rubric_l4"),
                        "rubric_l5": s.get("rubric_l5"),
                    }
                    for i, s in enumerate(skills_data)
                ]

                try:
                    if cache_key in cache:
                        cached_entry = cache[cache_key]
                        bp_data = cached_entry["bp_data"]
                        elapsed = cached_entry.get("elapsed", 0.0)
                        print(f"  [CACHE] [{r_key}] [{sen}] loaded")
                    else:
                        print(f"  [GENERATING] [{r_key}] [{sen}]...")
                        bp_data = None
                        for attempt in range(2):
                            try:
                                bp_data = await generate_job_blueprint(
                                    job_id=f"test_{r_key}_{sen}",
                                    job_title=f"{tpl.display_name} ({sen.capitalize()})",
                                    seniority_level=sen,
                                    duration_mins=20,
                                    skills=skills_payload,
                                    job_description=tpl.description,
                                )
                                break
                            except Exception as e_gen:
                                if attempt == 1:
                                    raise e_gen
                                print(f"  [RETRYING] [{r_key}] [{sen}] due to: {e_gen}")
                                await asyncio.sleep(2.0)

                        elapsed = time.time() - t0
                        # serialize SkillSectionContent inside sections before caching
                        cache_sections = []
                        for s in bp_data.get("sections", []):
                            s_copy = dict(s)
                            if "content" in s_copy and hasattr(s_copy["content"], "model_dump"):
                                s_copy["content"] = s_copy["content"].model_dump()
                            cache_sections.append(s_copy)
                        bp_cacheable = dict(bp_data)
                        bp_cacheable["sections"] = cache_sections
                        cache[cache_key] = {"bp_data": bp_cacheable, "elapsed": elapsed}
                        matrix_cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")

                    # Validate blueprint
                    val_report = validate_blueprint(
                        sections=bp_data.get("sections", []),
                        job_skills=skills_payload,
                        active_skill_time=bp_data.get("active_skill_mins", 14.0),
                        total_duration_mins=bp_data.get("total_duration_mins", 20),
                        seniority_level=sen,
                    )
                    metrics = val_report.metrics or {}

                    matrix_rows.append({
                        "role": tpl.display_name,
                        "role_key": r_key,
                        "seniority": sen.capitalize(),
                        "skills_count": len(skills_data),
                        "p0_count": metrics.get("p0_skills_count", sum(1 for s in skills_data if s["priority_tier"] == "P0")),
                        "core_capacity": metrics.get("core_capacity_questions", 8),
                        "is_valid": "✅ PASS" if val_report.is_valid else "❌ FAIL",
                        "errors": len(val_report.errors),
                        "warnings": len(val_report.warnings),
                        "latency_s": f"{elapsed:.2f}s",
                    })
                    print(f"  [{r_key}] [{sen}]: Valid={val_report.is_valid}, Errors={len(val_report.errors)}, Warnings={len(val_report.warnings)} ({elapsed:.2f}s)")
                except Exception as row_exc:
                    print(f"  ❌ [{r_key}] [{sen}] FAILED: {row_exc}")
                    matrix_rows.append({
                        "role": tpl.display_name,
                        "role_key": r_key,
                        "seniority": sen.capitalize(),
                        "skills_count": len(skills_data),
                        "p0_count": sum(1 for s in skills_data if s["priority_tier"] == "P0"),
                        "core_capacity": 8,
                        "is_valid": "❌ FAIL",
                        "errors": 1,
                        "warnings": 0,
                        "latency_s": "ERR",
                    })

    # Print Table
    print("\n" + "=" * 95)
    print("4x3 Matrix Validator Summary Table (4 Templates x 3 Seniorities)")
    print("=" * 95)
    header = f"{'Role Template':<28} | {'Seniority':<8} | {'Skills':<6} | {'P0 Tier':<7} | {'Status':<8} | {'Errors':<6} | {'Warnings':<8} | {'Latency':<8}"
    print(header)
    print("-" * len(header))
    # Save to docs/MATRIX_SUMMARY.md
    md_lines = [
        "# 4x3 Matrix Validator Summary (4 Role Templates x 3 Seniorities)",
        "",
        "| Role Template | Seniority | Skills | P0 Tier | Validation | Errors | Warnings | Latency |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in matrix_rows:
        md_lines.append(f"| {r['role']} | {r['seniority']} | {r['skills_count']} | {r['p0_count']} | {r['is_valid']} | {r['errors']} | {r['warnings']} | {r['latency_s']} |")
    md_content = "\n".join(md_lines) + "\n"
    (ROOT_DIR / "docs" / "MATRIX_SUMMARY.md").write_text(md_content, encoding="utf-8")
    print(f"✓ Saved matrix summary to: {ROOT_DIR / 'docs' / 'MATRIX_SUMMARY.md'}")

    return matrix_rows


if __name__ == "__main__":
    asyncio.run(run_pipeline())
