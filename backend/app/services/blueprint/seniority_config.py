"""Shared Seniority Level Configuration for Budgeting, Generation, and Validation."""

from typing import Dict, Any, List

SENIORITY_PROFILES: Dict[str, Dict[str, Any]] = {
    "entry": {
        "key": "entry",
        "display_name": "Entry-Level",
        "core_levels": ["L2", "L3"],
        "stretch_levels": ["L4"],
        "target_level_min": "L2",
        "target_level_max": "L3",
        "target_rubric_tier": "L2-L3 Developing",
        "question_style_instructions": (
            "Anchor questions MUST be answerable with NO prior production experience (verbal problem-solving or hypothetical scenario, "
            "e.g. 'Suppose you receive a stream of data... how would you choose your data structures?'). "
            "Anchor Alt MUST be a simpler, more concrete version of the exact same scenario, used when the candidate is stuck or says they have no experience. "
            "Never require writing code aloud."
        ),
    },
    "mid": {
        "key": "mid",
        "display_name": "Mid-Level",
        "core_levels": ["L3", "L4"],
        "stretch_levels": ["L5"],
        "target_level_min": "L3",
        "target_level_max": "L4",
        "target_rubric_tier": "L3-L4 Proficient",
        "question_style_instructions": (
            "Experience, architectural trade-offs, debugging, and production edge cases. Never require writing code aloud."
        ),
    },
    "senior": {
        "key": "senior",
        "display_name": "Senior",
        "core_levels": ["L4"],
        "stretch_levels": ["L5"],
        "target_level_min": "L4",
        "target_level_max": "L5",
        "target_rubric_tier": "L4-L5 Strong",
        "question_style_instructions": (
            "Production trade-offs, scalability, failure modes, distributed debugging, and operational bounds. Never require writing code aloud."
        ),
    },
    "lead": {
        "key": "lead",
        "display_name": "Lead / Staff",
        "core_levels": ["L4", "L5"],
        "stretch_levels": ["L5"],
        "target_level_min": "L4",
        "target_level_max": "L5",
        "target_rubric_tier": "L5 Expert & Leadership",
        "question_style_instructions": (
            "High-impact system architecture, hardware/cost vs SLA balance, incident leadership, and engineering standards. Never require writing code aloud."
        ),
    },
}


def normalize_seniority(raw: str) -> str:
    """Normalize user or legacy seniority string to entry|mid|senior|lead."""
    if not raw:
        return "mid"
    s = raw.strip().lower()
    if "entry" in s or "intern" in s or "junior" in s or "l1" in s or "l2" in s or "l3" in s:
        return "entry"
    if "lead" in s or "staff" in s or "principal" in s or "l6" in s:
        return "lead"
    if "senior" in s or "l5" in s:
        return "senior"
    return "mid"


def get_seniority_profile(raw: str) -> Dict[str, Any]:
    """Retrieve full seniority profile config for a given seniority string."""
    norm = normalize_seniority(raw)
    return SENIORITY_PROFILES.get(norm, SENIORITY_PROFILES["mid"])
