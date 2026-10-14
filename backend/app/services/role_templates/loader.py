"""Role template services: loading, seeding, and applying role templates."""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import RoleTemplate

logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds" / "role_templates"


async def load_role_templates(db: AsyncSession) -> List[RoleTemplate]:
    """Idempotently seed and update role templates from JSON files in backend/app/seeds/role_templates/."""
    loaded = []
    if not SEEDS_DIR.exists():
        logger.warning(f"Seeds directory does not exist: {SEEDS_DIR}")
        return loaded

    json_files = sorted(SEEDS_DIR.glob("*.json"))
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            role_key = data["role_key"]
            version = data.get("version", 1)

            # Query existing template by (role_key, version)
            stmt = select(RoleTemplate).where(
                RoleTemplate.role_key == role_key,
                RoleTemplate.version == version,
            )
            existing = (await db.execute(stmt)).scalars().first()

            if existing:
                # Update in-place
                existing.display_name = data["display_name"]
                existing.description = data["description"]
                existing.default_duration_mins = data.get("default_duration_mins", 30)
                existing.default_interviewer_tone = data.get("default_interviewer_tone")
                existing.default_pacing = data.get("default_pacing", "Balanced")
                existing.suggested_certifications = data.get("suggested_certifications", [])
                existing.skills = data.get("skills", [])
                existing.seniority_profiles = data.get("seniority_profiles", {})
                existing.question_style_notes = data.get("question_style_notes", {})
                existing.is_active = data.get("is_active", True)
                loaded.append(existing)
            else:
                new_tpl = RoleTemplate(
                    role_key=role_key,
                    display_name=data["display_name"],
                    description=data["description"],
                    version=version,
                    default_duration_mins=data.get("default_duration_mins", 30),
                    default_interviewer_tone=data.get("default_interviewer_tone"),
                    default_pacing=data.get("default_pacing", "Balanced"),
                    suggested_certifications=data.get("suggested_certifications", []),
                    skills=data.get("skills", []),
                    seniority_profiles=data.get("seniority_profiles", {}),
                    question_style_notes=data.get("question_style_notes", {}),
                    is_active=data.get("is_active", True),
                )
                db.add(new_tpl)
                loaded.append(new_tpl)
        except Exception as e:
            logger.error(f"Failed to load role template from {file_path}: {e}")
            raise

    await db.commit()
    for tpl in loaded:
        await db.refresh(tpl)

    return loaded


async def get_all_role_templates(db: AsyncSession, active_only: bool = True) -> List[RoleTemplate]:
    """Retrieve all seeded role templates."""
    stmt = select(RoleTemplate).order_by(RoleTemplate.role_key)
    if active_only:
        stmt = stmt.where(RoleTemplate.is_active.is_(True))
    return (await db.execute(stmt)).scalars().all()


async def get_role_template_by_key(
    db: AsyncSession,
    role_key: str,
    version: Optional[int] = None,
) -> Optional[RoleTemplate]:
    """Retrieve a single role template by key and optional version."""
    stmt = select(RoleTemplate).where(RoleTemplate.role_key == role_key)
    if version:
        stmt = stmt.where(RoleTemplate.version == version)
    else:
        stmt = stmt.order_by(RoleTemplate.version.desc())
    return (await db.execute(stmt)).scalars().first()


async def get_role_template_by_id(db: AsyncSession, template_id: str) -> Optional[RoleTemplate]:
    """Retrieve a single role template by its UUID."""
    stmt = select(RoleTemplate).where(RoleTemplate.id == template_id)
    return (await db.execute(stmt)).scalars().first()


def extract_template_skills_for_seniority(
    template: RoleTemplate,
    seniority: str,
) -> List[Dict[str, Any]]:
    """Extract and configure job skills from a role template for a given seniority level."""
    s_norm = seniority.lower().strip()
    if "entry" in s_norm or "intern" in s_norm or "junior" in s_norm:
        seniority_key = "entry"
    elif "lead" in s_norm or "staff" in s_norm or "principal" in s_norm:
        seniority_key = "lead"
    elif "senior" in s_norm:
        seniority_key = "senior"
    else:
        seniority_key = "mid"

    profiles = template.seniority_profiles or {}
    profile = profiles.get(seniority_key, {})

    all_skills = template.skills or []
    result = []

    for skill_def in all_skills:
        skey = skill_def.get("key")
        skill_cfg = profile.get(skey)
        if not skill_cfg or not skill_cfg.get("included", False):
            continue

        result.append({
            "template_skill_key": skey,
            "name": skill_def.get("name"),
            "category": skill_def.get("category", "Core Technical"),
            "priority_tier": skill_cfg.get("tier", "P0"),
            "weight_percentage": float(skill_cfg.get("weight", 0.0)),
            "target_level_min": skill_cfg.get("target_level_min", "L3"),
            "target_level_max": skill_cfg.get("target_level_max", "L4"),
            "source": "template",
            "description": skill_def.get("description", ""),
            "rubric_l1": skill_def.get("rubric_l1"),
            "rubric_l2": skill_def.get("rubric_l2"),
            "rubric_l3": skill_def.get("rubric_l3"),
            "rubric_l4": skill_def.get("rubric_l4"),
            "rubric_l5": skill_def.get("rubric_l5"),
            "expectation_bank": skill_def.get("expectation_bank", {}),
            "question_patterns": skill_def.get("question_patterns", {}),
        })

    return result
