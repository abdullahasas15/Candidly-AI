import asyncio
import json
import time
from backend.app.database import AsyncSessionLocal
from backend.app.models import JobPosting
from backend.app.services.blueprint.generator import generate_job_blueprint
from backend.app.services.blueprint.persistence import save_job_blueprint
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def run_test():
    async with AsyncSessionLocal() as session:
        stmt = (
            select(JobPosting)
            .where(JobPosting.id == "c4f40b04-77e4-4776-9381-cf659391bee9")
            .options(selectinload(JobPosting.skills))
        )
        res = await session.execute(stmt)
        job = res.scalars().first()
        
        print(f"Generating Blueprint for: {job.job_title} | Level: {job.seniority_level} | Duration: {job.interview_duration_mins}m")
        skills_data = [
            {
                "id": s.id,
                "name": s.name,
                "category": s.category,
                "priority_tier": s.priority_tier,
                "weight_percentage": s.weight_percentage,
                "target_level_min": s.target_level_min,
                "target_level_max": s.target_level_max,
                "rubric_l1": s.rubric_l1,
                "rubric_l2": s.rubric_l2,
                "rubric_l3": s.rubric_l3,
                "rubric_l4": s.rubric_l4,
                "rubric_l5": s.rubric_l5,
            }
            for s in job.skills
        ]

        def on_prog(stage, prog, sec_data):
            s_name = sec_data.get("skill_name") if sec_data else "None"
            print(f"  [Progress] Stage: {stage:20s} ({prog*100:5.1f}%) | Skill: {s_name}")

        t0 = time.perf_counter()
        bp_data = await generate_job_blueprint(
            job_id=job.id,
            job_title=job.job_title,
            seniority_level=job.seniority_level,
            duration_mins=job.interview_duration_mins,
            skills=skills_data,
            job_description=job.job_description,
            progress_callback=on_prog,
        )
        total_dur = (time.perf_counter() - t0) * 1000.0

        val_rep = bp_data.get("validation_report", {})
        errors = val_rep.get("errors", [])
        warnings = val_rep.get("warnings", [])

        print("\n" + "=" * 70)
        print("MEASURED BLUEPRINT GENERATION METRICS:")
        print(f"  Job: {job.job_title} ({job.seniority_level})")
        print(f"  Duration Used: {bp_data.get('total_duration_mins')} minutes")
        print(f"  Provider: {bp_data.get('generation_provider')}")
        print(f"  Model: {bp_data.get('generation_model')}")
        print(f"  Generated with Backup: {bp_data.get('is_generated_with_backup')}")
        print(f"  Total Duration: {total_dur:.1f}ms")
        print(f"  Stage Timings (ms): {json.dumps(bp_data.get('generation_stages_ms'), indent=4)}")
        print(f"  Validation Errors: {len(errors)}")
        print(f"  Validation Warnings: {len(warnings)}")
        if errors:
            print("  Errors:")
            for e in errors:
                print(f"    - {e}")
        if warnings:
            print("  Warnings:")
            for w in warnings:
                print(f"    - {w}")

        print("\n" + "=" * 70)
        print("SECTIONS & PROMPTS INSPECTION:")
        for idx, s in enumerate(bp_data.get("sections", [])):
            stype = s.get("section_type")
            title = s.get("title")
            mins = s.get("allocated_minutes")
            print(f"\nSection {idx}: [{stype}] {title} ({mins} mins)")
            content = s.get("content")
            if content:
                anchor = getattr(content, "anchor_question", None)
                alt = getattr(content, "anchor_alt_question", None)
                esc = getattr(content, "escalation_question", None)
                probes = getattr(content, "probes", [])
                if anchor:
                    print(f"  Anchor:     {anchor.question_text}")
                if alt:
                    print(f"  Anchor Alt: {alt.question_text}")
                if esc:
                    print(f"  Escalation: {esc.question_text}")
                print(f"  Probes ({len(probes)} total):")
                for p in probes[:3]:
                    print(f"    - [{p.trigger_condition}]: {p.question_text}")

        # Save to DB to test persistence
        saved_bp = await save_job_blueprint(
            db=session,
            blueprint_data=bp_data,
            auto_approve=False,
        )
        print(f"\n✓ Successfully saved draft Blueprint ID: {saved_bp.id} (version {saved_bp.version})")

if __name__ == "__main__":
    asyncio.run(run_test())
