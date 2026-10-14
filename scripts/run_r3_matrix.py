#!/usr/bin/env python3
"""R3.0 Matrix Re-run Script:
Executes the full generation and validation pipeline across 4 templates x 3 seniority levels (12 blueprints)
without cache, measures generation times, aggregates warnings by type, and dumps SDE Entry data-structures section.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.database import AsyncSessionLocal
from backend.app.services.role_templates import (
    load_role_templates,
    get_all_role_templates,
    extract_template_skills_for_seniority,
)
from backend.app.services.blueprint.generator import generate_job_blueprint
from backend.app.services.blueprint.validator import validate_blueprint


async def main():
    print("=" * 70)
    print("Starting R3.0 Matrix Re-run (4 templates x 3 seniorities = 12 Blueprints)")
    print("=" * 70)

    async with AsyncSessionLocal() as session:
        await load_role_templates(session)
        templates_map = {t.role_key: t for t in await get_all_role_templates(session)}

    roles = ["sde", "ai_engineer", "devops", "data_engineer"]
    seniorities = ["entry", "mid", "senior"]

    results = []
    warning_counts_by_type = {}
    error_counts_by_type = {}
    sde_entry_data_structures = None

    for role_key in roles:
        tpl = templates_map[role_key]
        for sen in seniorities:
            combo_name = f"{role_key}_{sen}"
            print(f"\nGenerating {combo_name} ({tpl.display_name} - {sen.upper()})...")

            skills_data = extract_template_skills_for_seniority(tpl, sen)
            skills_payload = [
                {
                    "id": f"temp_{i}",
                    "name": s["name"],
                    "category": s["category"],
                    "priority_tier": s["priority_tier"],
                    "weight_percentage": s["weight_percentage"],
                    "target_level_min": s.get("target_level_min"),
                    "target_level_max": s.get("target_level_max"),
                    "rubric_l1": s.get("rubric_l1"),
                    "rubric_l2": s.get("rubric_l2"),
                    "rubric_l3": s.get("rubric_l3"),
                    "rubric_l4": s.get("rubric_l4"),
                    "rubric_l5": s.get("rubric_l5"),
                }
                for i, s in enumerate(skills_data)
            ]

            t0 = time.perf_counter()
            bp_data = await generate_job_blueprint(
                job_id=f"matrix_{combo_name}",
                job_title=f"{tpl.display_name} ({sen.capitalize()})",
                seniority_level=sen,
                duration_mins=20 if sen == "entry" else 30,
                skills=skills_payload,
                job_description=tpl.description,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            val_rep = bp_data.get("validation_report", {})
            errors = val_rep.get("errors", [])
            warnings = val_rep.get("warnings", [])

            for w in warnings:
                # Group warning type
                w_key = w.split(":")[0] if ":" in w else w[:45]
                warning_counts_by_type[w_key] = warning_counts_by_type.get(w_key, 0) + 1

            for e in errors:
                e_key = e.split(":")[0] if ":" in e else e[:45]
                error_counts_by_type[e_key] = error_counts_by_type.get(e_key, 0) + 1

            provider = bp_data.get("generation_provider")
            model = bp_data.get("generation_model")
            backup = bp_data.get("is_generated_with_backup")

            print(f"  ✓ {combo_name}: {elapsed_ms:.1f}ms | Provider={provider} ({model}) | Backup={backup} | Errors={len(errors)} | Warnings={len(warnings)}")

            results.append({
                "combo": combo_name,
                "role": tpl.display_name,
                "seniority": sen,
                "elapsed_ms": elapsed_ms,
                "provider": provider,
                "model": model,
                "backup_used": backup,
                "errors_count": len(errors),
                "warnings_count": len(warnings),
                "errors": errors,
                "warnings": warnings,
                "stage_timings": bp_data.get("generation_stages_ms", {}),
            })

            # Capture SDE Entry Data Structures section
            if combo_name == "sde_entry":
                for sec in bp_data.get("sections", []):
                    s_name = (sec.get("skill_name") or sec.get("title") or "").lower()
                    if "data structure" in s_name or "problem solving" in s_name:
                        content = sec.get("content")
                        if content:
                            anchor = getattr(content, "anchor_question", None)
                            alt = getattr(content, "anchor_alt_question", None)
                            esc = getattr(content, "escalation_question", None)
                            probes = getattr(content, "probes", [])
                            sde_entry_data_structures = {
                                "title": sec.get("title"),
                                "allocated_minutes": sec.get("allocated_minutes"),
                                "anchor": anchor.question_text if anchor else None,
                                "anchor_alt": alt.question_text if alt else None,
                                "anchor_alt_trigger": getattr(alt, "trigger_condition", None) if alt else None,
                                "escalation": esc.question_text if esc else None,
                                "probes": [
                                    {
                                        "text": p.question_text,
                                        "trigger": getattr(p, "trigger_condition", None),
                                        "targets": getattr(p, "target_expectation_indices", []),
                                    }
                                    for p in probes
                                ],
                            }

    print("\n" + "=" * 85)
    print("R3.1 MATRIX RESULTS SUMMARY:")
    print("=" * 85)
    print(f"{'Combination':<20} | {'Seniority':<8} | {'Latency (ms)':<12} | {'Provider':<12} | {'Model':<25} | {'Errors':<6} | {'Warnings':<8}")
    print("-" * 105)
    for r in results:
        print(f"{r['combo']:<20} | {r['seniority']:<8} | {r['elapsed_ms']:<12.1f} | {str(r['provider']):<12} | {str(r['model']):<25} | {r['errors_count']:<6} | {r['warnings_count']:<8}")

    print("\n" + "=" * 70)
    print("TOTAL ERRORS BY TYPE (Target: 0):")
    if not error_counts_by_type:
        print("  ✓ 0 errors across all 12 blueprints!")
    else:
        for k, v in error_counts_by_type.items():
            print(f"  - {k}: {v}")

    print("\n" + "=" * 70)
    print("TOTAL WARNINGS BY TYPE:")
    for k, v in sorted(warning_counts_by_type.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {k}: {v}")

    print("\n" + "=" * 70)
    print("SDE ENTRY: DATA STRUCTURES & PROBLEM SOLVING SECTION:")
    print("=" * 70)
    if sde_entry_data_structures:
        print(f"Section Title: {sde_entry_data_structures['title']} ({sde_entry_data_structures['allocated_minutes']}m)")
        print(f"Anchor:     {sde_entry_data_structures['anchor']}")
        print(f"Anchor Alt: {sde_entry_data_structures['anchor_alt']}")
        print(f"  Trigger:  {sde_entry_data_structures['anchor_alt_trigger']}")
        print(f"Escalation: {sde_entry_data_structures['escalation']}")
        print("Probes:")
        for idx, p in enumerate(sde_entry_data_structures['probes']):
            print(f"  Probe {idx+1}: [{p['trigger']}]")
            print(f"           {p['text']}")
    else:
        print("Warning: SDE Entry Data Structures section was not found!")

    # Write summary json to docs/r3_matrix_results.json
    out_path = ROOT_DIR / "docs" / "r3_matrix_results.json"
    out_path.write_text(json.dumps({
        "results": results,
        "warning_counts": warning_counts_by_type,
        "error_counts": error_counts_by_type,
        "sde_entry_data_structures": sde_entry_data_structures,
    }, indent=2), encoding="utf-8")
    print(f"\n✓ Saved full matrix report to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
