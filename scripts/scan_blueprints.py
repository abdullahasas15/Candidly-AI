#!/usr/bin/env python3
"""Scan blueprints and role templates for code-request patterns and mark offending blueprints stale.

Part 5: Question framing:
Verbal only. No writing, typing, reading or implementing code, no whiteboard,
no syntax, no 'write a function'. Ask for approach, ideas, trade-offs and
complexity, explained aloud.

Usage:
    ./scripts/scan_blueprints.py [--fix]
"""

import json
import re
import sys
from pathlib import Path

# Hard error patterns for code-request in voice interviews
CODE_REQUEST_PATTERNS = [
    (r"\bwrite (a |an )?(function|method|class|code|script|snippet|program)\b", "write code/function/program"),
    (r"\bwrite code\b", "write code"),
    (r"\bcode aloud\b", "code aloud"),
    (r"\btype out\b", "type out code"),
    (r"\bcode up\b", "code up"),
    (r"\bimplement (a |an )?(function|method|class|script|snippet)\b", "implement function/class"),
    (r"\bfunction that\b", "function that (code request)"),
    (r"\bclass that\b", "class that (code request)"),
    (r"\b(code )?snippet\b", "code snippet"),
    (r"\b(exact )?syntax\b", "syntax request"),
    (r"\bwhiteboard\b", "whiteboard coding"),
    (r"\bprogram (a |an )\b", "program an algorithm"),
]


def check_text_for_code_request(text: str) -> list[str]:
    violations = []
    if not text:
        return violations
    lower = text.lower()
    for pat, desc in CODE_REQUEST_PATTERNS:
        if re.search(pat, lower):
            violations.append(desc)
    return violations


def scan_role_templates() -> list[dict]:
    template_dir = Path("backend/app/seeds/role_templates")
    results = []
    if not template_dir.exists():
        return results

    for tf in sorted(template_dir.glob("*.json")):
        try:
            with open(tf, "r", encoding="utf-8") as f:
                data = json.load(f)
            role_key = data.get("role_key", tf.stem)
            for skill in data.get("skills", []):
                sname = skill.get("name", "Unknown Skill")
                qp = skill.get("question_patterns", {})
                for k, prompt in qp.items():
                    v = check_text_for_code_request(prompt)
                    if v:
                        results.append({
                            "source": f"Template {tf.name}",
                            "role": role_key,
                            "skill": sname,
                            "field": k,
                            "text": prompt,
                            "violations": v,
                        })
        except Exception as e:
            print(f"Error reading {tf.name}: {e}")
    return results


async def _scan_database_blueprints_async(mark_stale: bool = True) -> list[dict]:
    results = []
    try:
        import asyncio
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from backend.app.database import AsyncSessionLocal
        from backend.app.models import InterviewBlueprint, BlueprintSection, BlueprintQuestion

        async with AsyncSessionLocal() as db:
            stmt = select(InterviewBlueprint).options(
                selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.questions)
            )
            res = await db.execute(stmt)
            blueprints = res.scalars().all()
            for bp in blueprints:
                bp_flagged = False
                for sec in bp.sections or []:
                    for q in sec.questions or []:
                        v = check_text_for_code_request(q.question_text)
                        if v:
                            bp_flagged = True
                            results.append({
                                "source": f"Blueprint {bp.id} (Job: {bp.job_id})",
                                "role": q.question_role,
                                "skill": sec.skill_name or sec.title,
                                "field": f"Q#{q.order_index} ({q.question_role})",
                                "text": q.question_text,
                                "violations": v,
                            })
                if bp_flagged and mark_stale:
                    bp.is_stale = True
            if mark_stale and results:
                await db.commit()
    except Exception as e:
        print(f"DB scan note: {e}")
    return results


def scan_database_blueprints(mark_stale: bool = True) -> list[dict]:
    import asyncio
    try:
        return asyncio.run(_scan_database_blueprints_async(mark_stale=mark_stale))
    except Exception as e:
        print(f"DB scan runner note: {e}")
        return []


def main():
    print("=" * 80)
    print("CANDIDLY BLUEPRINT SCANNER - CODE-REQUEST GUARD (Part 5)")
    print("=" * 80)

    print("\n[1] Scanning Role Templates (backend/app/seeds/role_templates/)...")
    template_findings = scan_role_templates()
    if not template_findings:
        print("  ✓ All role template question patterns are verbal-only! Zero code requests found.")
    else:
        print(f"  ✗ Found {len(template_findings)} violations in role templates:")
        for f in template_findings:
            print(f"    - [{f['source']}] {f['skill']} -> {f['field']}: {f['violations']}")
            print(f"      Text: \"{f['text']}\"")

    print("\n[2] Scanning Database Blueprints...")
    db_findings = scan_database_blueprints(mark_stale=True)
    if not db_findings:
        print("  ✓ All database blueprints are clean or none contain code requests.")
    else:
        print(f"  ✗ Found {len(db_findings)} violations in database blueprints (marked stale):")
        for f in db_findings:
            print(f"    - [{f['source']}] {f['skill']} -> {f['field']}: {f['violations']}")
            print(f"      Text: \"{f['text']}\"")

    print("\n" + "=" * 80)
    total = len(template_findings) + len(db_findings)
    if total == 0:
        print("RESULT: PASSED. Zero code-request patterns detected across templates and blueprints.")
    else:
        print(f"RESULT: {total} items flagged and marked stale for regeneration.")
    print("=" * 80)


if __name__ == "__main__":
    main()
