"""Centralized Prompt Template Loader.

Strictly loads templates from the backend/app/prompts directory using Python's
string.Template syntax ($variable or ${variable}). Braces for raw JSON objects
remain intact without escaping.
"""

import os
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Set

PROMPT_VERSION_PLAN = "interview_plan.v1"
PROMPT_VERSION_SELECTOR = "interview_selector.v1"
PROMPT_VERSION_QA = "interview_qa.v1"
PROMPT_VERSION_ACK = "interview_ack.v1"

PROMPTS_ROOT = Path(__file__).resolve().parent


class PromptTemplateError(Exception):
    """Raised when a prompt template is missing, invalid, or missing required variables."""
    pass


def _resolve_template_path(name: str) -> Path:
    clean_name = name.strip().lstrip("/")
    if not clean_name.endswith(".tmpl"):
        clean_name += ".tmpl"

    target_path = (PROMPTS_ROOT / clean_name).resolve()

    # Prevent directory traversal attacks
    try:
        target_path.relative_to(PROMPTS_ROOT)
    except ValueError:
        raise PromptTemplateError(f"Disallowed template path traversal: {name}")

    if not target_path.is_file():
        raise PromptTemplateError(f"Prompt template file not found: {target_path}")

    return target_path


def render_prompt(name: str, **kwargs: Any) -> str:
    """Load and substitute a template by name with strict variable validation.

    Example:
        render_prompt("interview/plan_generation_system", model_name="nova-pro")
    """
    path = _resolve_template_path(name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    except Exception as e:
        raise PromptTemplateError(f"Failed to read template '{name}': {e}") from e

    tmpl = Template(raw_content)
    try:
        return tmpl.substitute(**kwargs)
    except KeyError as e:
        raise PromptTemplateError(
            f"Missing required template variable {e} in prompt template '{name}'"
        ) from e
    except ValueError as e:
        raise PromptTemplateError(
            f"Invalid placeholder syntax in prompt template '{name}': {e}"
        ) from e


def get_template_variables(name: str) -> Set[str]:
    """Inspect and return the set of placeholder variable names in a template."""
    path = _resolve_template_path(name)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    tmpl = Template(content)
    # Extract identifier names from regex matches in Template
    vars_found = set()
    for match in tmpl.pattern.finditer(content):
        # groups: (escaped, named, braced, invalid)
        named = match.group('named') or match.group('braced')
        if named:
            vars_found.add(named)
    return vars_found


def validate_all_templates() -> Dict[str, List[str]]:
    """Scan all .tmpl files in the prompts package and verify they compile cleanly."""
    results: Dict[str, List[str]] = {}
    for tmpl_file in PROMPTS_ROOT.rglob("*.tmpl"):
        rel_path = tmpl_file.relative_to(PROMPTS_ROOT).as_posix()
        name_no_ext = rel_path[:-5] if rel_path.endswith(".tmpl") else rel_path
        try:
            vars_found = sorted(get_template_variables(name_no_ext))
            results[name_no_ext] = vars_found
        except Exception as e:
            raise PromptTemplateError(f"Validation failed on template '{rel_path}': {e}") from e
    return results
