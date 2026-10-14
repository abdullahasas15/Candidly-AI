#!/usr/bin/env python3
"""Dumps a Job Interview Blueprint into readable markdown.

Usage:
    ./.venv/bin/python scripts/dump_blueprint.py <job_id>
"""

import asyncio
import os
import sys
from typing import Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal
from backend.app.models import JobPosting, InterviewBlueprint, BlueprintSection
from backend.app.services.blueprint.persistence import (
    get_job_blueprint,
    serialize_blueprint,
    compute_job_input_hash,
)
from backend.app.services.blueprint.validator import (
    validate_blueprint,
    VAGUE_SKILL_NAMES,
)


def format_blueprint_markdown(job: JobPosting, bp: InterviewBlueprint, serialized: dict, val_report) -> str:
    md = []
    md.append(f"# Job Interview Blueprint: {job.job_title}")
    md.append(f"- **Job ID**: `{job.id}`")
    md.append(f"- **Role Key**: `{getattr(job, 'role_key', 'custom')}`")
    md.append(f"- **Department**: {job.department}")
    md.append(f"- **Seniority Level**: {job.seniority_level}")
    md.append(f"- **Total Duration**: {bp.total_duration_mins} minutes")
    md.append(f"- **Blueprint Version**: v{bp.version} ({bp.status.upper()})")
    md.append(f"- **Blueprint ID**: `{bp.id}`")
    md.append(f"- **Is Stale**: {'⚠️ YES (Blueprint Out of Date)' if serialized.get('is_stale') else '✅ NO (Up to Date)'}")
    md.append(f"- **Input Hash**: `{bp.input_hash or 'None'}`")
    if bp.approved_at:
        md.append(f"- **Approved At**: {bp.approved_at.isoformat()}")
    md.append("")

    # Vague skills warning check
    vague_skills = [
        s.name for s in (job.skills or [])
        if s.name and (s.name.strip().lower() in VAGUE_SKILL_NAMES or len(s.name.strip()) < 3)
    ]
    if vague_skills:
        md.append("> [!WARNING]")
        md.append(f"> **Vague Skill Name Detected**: `{', '.join(vague_skills)}`.")
        md.append("> Skill names should be specific (e.g. 'Production Projects & Architecture' instead of generic 'projects').")
        md.append("")

    # Budget Metrics
    metrics = val_report.metrics or {}
    md.append("## Budget & Capacity Metrics")
    md.append(f"| Metric | Value |")
    md.append(f"| :--- | :--- |")
    md.append(f"| Total Duration | {bp.total_duration_mins} mins |")
    md.append(f"| Active Skill Assessment Time | {bp.active_skill_mins} mins |")
    md.append(f"| Fixed Overhead (Welcome/Intro/QA/Closing) | {bp.fixed_overhead_mins} mins |")
    md.append(f"| Total Expectations | {metrics.get('total_expectations', 0)} (Core: {metrics.get('core_expectations', 0)}) |")
    md.append(f"| Expected Capacity (~2.0m / exp) | {metrics.get('expected_capacity', 0)} |")
    md.append(f"| Reachability Density Ratio | {metrics.get('reachability_ratio', 0)} |")
    md.append("")

    # Sections
    md.append("## Interview Structure & Spoken Script")
    for sec in serialized.get("sections", []):
        sec_type = sec.get("section_type")
        mins = sec.get("allocated_minutes")
        title = sec.get("title")

        if sec_type == "welcome":
            md.append(f"### [Section {sec['order_index'] + 1}] Welcome & Candidate Setup ({mins}m)")
            md.append("**Spoken Welcome Script:**")
            md.append(f"> \"{sec.get('welcome_script')}\"")
            md.append("")
        elif sec_type == "intro":
            md.append(f"### [Section {sec['order_index'] + 1}] Candidate Introduction & Career Journey ({mins}m)")
            md.append("_Candidate self-introduction, journey overview, and key technical focus areas._")
            md.append("")
        elif sec_type == "candidate_qa":
            md.append(f"### [Section {sec['order_index'] + 1}] Candidate Q&A ({mins}m)")
            md.append("_Candidate asks questions about the team, role, and engineering stack._")
            md.append("")
        elif sec_type == "closing":
            md.append(f"### [Section {sec['order_index'] + 1}] Session Wrap-up & Closing ({mins}m)")
            md.append("**Spoken Closing Script:**")
            md.append(f"> \"{sec.get('closing_script')}\"")
            md.append("")
        elif sec_type == "skill":
            skill_name = sec.get("skill_name") or title
            p_tier = sec.get("priority_tier", "P1")
            is_vague = skill_name.strip().lower() in VAGUE_SKILL_NAMES
            vague_tag = " ⚠️ [VAGUE SKILL]" if is_vague else ""

            md.append(f"### [Section {sec['order_index'] + 1}] Skill: {skill_name} ({mins}m, {p_tier}){vague_tag}")

            # Expectations
            md.append("#### Evaluated Expectations:")
            exps = sec.get("expectations", [])
            for e_idx, exp in enumerate(exps):
                imp = exp.get("importance", "core").upper()
                level = exp.get("source_rubric_level", "L4")
                md.append(f"{e_idx + 1}. **[{imp} | {level}]** {exp.get('expectation_text')}")
            md.append("")

            # Questions
            questions = sec.get("questions", [])
            anchors = [q for q in questions if q.get("question_role") == "anchor"]
            anchor_alts = [q for q in questions if q.get("question_role") == "anchor_alt"]
            escalations = [q for q in questions if q.get("question_role") == "escalation"]
            probes = [q for q in questions if q.get("question_role") == "probe"]

            if anchors:
                a = anchors[0]
                src = f" (Source: {a.get('source', 'llm')})" if a.get("source") != "llm" else ""
                md.append(f"**Anchor Question** ({a.get('word_count', 0)} words){src}:")
                md.append(f"> \"{a.get('question_text')}\"")
                md.append("")

            if anchor_alts:
                alt = anchor_alts[0]
                md.append(f"**Anchor Alt Question (Hypothetical)** ({alt.get('word_count', 0)} words):")
                md.append(f"> \"{alt.get('question_text')}\"")
                md.append("")

            if escalations:
                esc = escalations[0]
                md.append(f"**Escalation Question** ({esc.get('word_count', 0)} words):")
                md.append(f"> \"{esc.get('question_text')}\"")
                md.append("")

            if probes:
                md.append(f"**Probes with Trigger Conditions ({len(probes)} total):**")
                for p_idx, p in enumerate(probes):
                    target_ids = p.get("target_expectation_ids", [])
                    matched_exps = []
                    for e_idx, exp in enumerate(exps):
                        if exp.get("id") in target_ids or str(e_idx) in [str(t) for t in target_ids]:
                            matched_exps.append(f"#{e_idx + 1}")
                    target_str = f"Target Exp {', '.join(matched_exps)}" if matched_exps else "General"

                    md.append(f"- **Probe {p_idx + 1}** ({p.get('word_count', 0)} words | {target_str}):")
                    md.append(f"  - *Trigger Condition*: `{p.get('trigger_condition')}`")
                    md.append(f"  - *Spoken Probe*: \"{p.get('question_text')}\"")
                md.append("")

    # Validation Report
    md.append("## Validation & Voice Rules Audit")
    md.append(f"- **Status**: {'✅ VALID' if val_report.is_valid else '❌ INVALID (APPROVAL BLOCKED)'}")
    if val_report.errors:
        md.append("- **Errors**:")
        for err in val_report.errors:
            md.append(f"  - 🔴 {err}")
    if val_report.warnings:
        md.append("- **Warnings**:")
        for warn in val_report.warnings:
            md.append(f"  - ⚠️ {warn}")
    if not val_report.errors and not val_report.warnings:
        md.append("- No errors or warnings detected.")

    return "\n".join(md)


async def main():
    if len(sys.argv) < 2:
        print("Usage: ./.venv/bin/python scripts/dump_blueprint.py <job_id>")
        sys.exit(1)

    job_id = sys.argv[1].strip()

    async with AsyncSessionLocal() as db:
        job_stmt = select(JobPosting).where(JobPosting.id == job_id).options(selectinload(JobPosting.skills))
        res = await db.execute(job_stmt)
        job = res.scalars().first()
        if not job:
            print(f"Error: Job '{job_id}' not found in database.")
            sys.exit(1)

        bp = await get_job_blueprint(db, job_id)
        if not bp:
            print(f"No blueprint exists for job '{job.job_title}' ({job.id}).")
            sys.exit(1)

        serialized = serialize_blueprint(bp, current_job=job)
        job_skills_data = [
            {"id": s.id, "name": s.name, "priority_tier": s.priority_tier, "weight_percentage": s.weight_percentage}
            for s in (job.skills or [])
        ]
        val_report = validate_blueprint(
            sections=serialized.get("sections", []),
            job_skills=job_skills_data,
            active_skill_time=bp.active_skill_mins,
            total_duration_mins=bp.total_duration_mins,
            seniority_level=job.seniority_level,
        )

        output_md = format_blueprint_markdown(job, bp, serialized, val_report)
        print(output_md)


if __name__ == "__main__":
    asyncio.run(main())
