"""Role Templates package."""

from .loader import (
    load_role_templates,
    get_all_role_templates,
    get_role_template_by_key,
    get_role_template_by_id,
    extract_template_skills_for_seniority,
)

__all__ = [
    "load_role_templates",
    "get_all_role_templates",
    "get_role_template_by_key",
    "get_role_template_by_id",
    "extract_template_skills_for_seniority",
]
