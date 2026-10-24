"""Centralized Prompt Template Package for Candidly.

Uses Python string.Template exclusively so that raw JSON braces inside
prompts remain literal without interfering with template variable interpolation.
"""

from .loader import (
    PromptTemplateError,
    render_prompt,
    validate_all_templates,
    get_template_variables,
    PROMPT_VERSION_PLAN,
    PROMPT_VERSION_SELECTOR,
    PROMPT_VERSION_QA,
    PROMPT_VERSION_ACK,
)

__all__ = [
    "PromptTemplateError",
    "render_prompt",
    "validate_all_templates",
    "get_template_variables",
    "PROMPT_VERSION_PLAN",
    "PROMPT_VERSION_SELECTOR",
    "PROMPT_VERSION_QA",
    "PROMPT_VERSION_ACK",
]
