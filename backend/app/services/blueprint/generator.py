"""Generator for Job Interview Blueprints using Gemini AI structured output."""

import asyncio
import json
import logging
import os
import re
import time
from typing import Dict, Any, List, Optional
from google.genai import types

from backend.app.budgeting import calculate_blueprint_section_budgets
from backend.app.services.question_generation.provider import get_gemini_client
from backend.app.services.blueprint.contracts import (
    SkillSectionContent,
    ExpectationDraft,
    QuestionDraft,
    ValidationReport,
)
from backend.app.services.blueprint.prompts import (
    SKILL_SECTION_SYSTEM_PROMPT,
    build_welcome_script,
    build_closing_script,
    build_skill_section_user_prompt,
    build_repair_user_prompt,
)
from backend.app.services.blueprint.validator import (
    extract_keywords,
    validate_skill_section,
    validate_blueprint,
)
from backend.app.services.blueprint.seniority_config import normalize_seniority

logger = logging.getLogger(__name__)


class SectionContentError(ValueError):
    """Raised when model output cannot be normalized into a complete section.

    The payload is retained so the generator can send it back to the model for
    a targeted repair pass. We never substitute generic placeholder questions.
    """

    def __init__(self, errors: List[str], payload: Optional[Dict[str, Any]] = None):
        self.errors = errors or ["Section output is incomplete"]
        self.payload = payload or {}
        super().__init__("; ".join(self.errors))


def _as_clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_rubric_level(value: Any, default: str = "L4") -> str:
    raw = _as_clean_text(value)
    match = re.search(r"([1-5])", raw)
    return f"L{match.group(1)}" if match else default


def _expectation_importance(item: Dict[str, Any]) -> str:
    for key in ("stretch", "is_stretch", "stretch_expectation"):
        if key in item:
            value = item.get(key)
            if isinstance(value, bool):
                return "stretch" if value else "core"
            if str(value).strip().lower() in {"true", "yes", "1", "stretch"}:
                return "stretch"

    raw = (
        item.get("importance")
        or item.get("tier")
        or item.get("priority")
        or item.get("expectation_type")
        or "core"
    )
    cleaned = str(raw).strip().lower()
    return "stretch" if "stretch" in cleaned or "optional" in cleaned or "nice" in cleaned else "core"


def _normalize_expectation_item(
    item: Any,
    default_level: Optional[str] = None,
    default_importance: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {
            "expectation_text": text,
            "source_rubric_level": _normalize_rubric_level(default_level),
            "importance": default_importance or "core",
        }

    if not isinstance(item, dict):
        return None

    text = (
        item.get("expectation_text")
        or item.get("text")
        or item.get("description")
        or item.get("expectation")
        or item.get("criterion")
        or item.get("requirement")
        or ""
    )
    text = str(text).strip()
    if not text:
        return None

    level = (
        item.get("source_rubric_level")
        or item.get("rubric_level")
        or item.get("level")
        or item.get("target_level")
        or default_level
    )
    importance = _expectation_importance(item)
    if default_importance and not any(
        key in item for key in ("importance", "tier", "priority", "stretch", "is_stretch")
    ):
        importance = default_importance

    return {
        "expectation_text": text,
        "source_rubric_level": _normalize_rubric_level(level),
        "importance": importance,
    }


def _apply_expectation_caps(expectations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep a deterministic 3-core / 2-stretch maximum without dropping content.

    Extra core items are reclassified as stretch (and vice versa) because the
    model commonly marks advanced L4/L5 items as core. If more than five items
    are returned, the tail is dropped and target indices are clamped later.
    """
    items = list(expectations[:5])
    if not items:
        return items

    selected: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    core_count = 0
    stretch_count = 0

    for original_index, item in enumerate(items):
        marked = dict(item)
        marked["_original_index"] = original_index
        if marked.get("importance") == "stretch" and stretch_count < 2:
            selected.append(marked)
            stretch_count += 1
        elif marked.get("importance") == "core" and core_count < 3:
            selected.append(marked)
            core_count += 1
        else:
            deferred.append(marked)

    for item in deferred:
        if core_count < 3:
            item["importance"] = "core"
            selected.append(item)
            core_count += 1
        elif stretch_count < 2:
            item["importance"] = "stretch"
            selected.append(item)
            stretch_count += 1
        else:
            break

    selected.sort(key=lambda x: x["_original_index"])
    for item in selected:
        item.pop("_original_index", None)

    if selected and not any(item["importance"] == "core" for item in selected):
        selected[0]["importance"] = "core"
    return selected


_QUESTION_ROLE_ALIASES = {
    "anchor": "anchor",
    "anchor_question": "anchor",
    "primary": "anchor",
    "primary_question": "anchor",
    "main_question": "anchor",
    "opening_question": "anchor",
    "base_question": "anchor",
    "anchor_alt": "anchor_alt",
    "anchor_alternative": "anchor_alt",
    "alternate_anchor": "anchor_alt",
    "alternative_question": "anchor_alt",
    "hypothetical": "anchor_alt",
    "hypothetical_question": "anchor_alt",
    "simpler_question": "anchor_alt",
    "fallback_question": "anchor_alt",
    "escalation": "escalation",
    "escalation_question": "escalation",
    "escalated_question": "escalation",
    "deeper_question": "escalation",
    "probe": "probe",
    "probe_question": "probe",
    "follow_up": "probe",
    "followup": "probe",
    "follow_up_question": "probe",
    "followup_probe": "probe",
    "clarifying_question": "probe",
}


def _canonical_question_role(value: Any) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", _as_clean_text(value).lower()).strip("_")
    if raw in _QUESTION_ROLE_ALIASES:
        return _QUESTION_ROLE_ALIASES[raw]
    if "anchor" in raw and any(part in raw for part in ("alt", "alternative", "hypo", "simpl", "fallback")):
        return "anchor_alt"
    if "anchor" in raw:
        return "anchor"
    if "escal" in raw or "deeper" in raw:
        return "escalation"
    if any(part in raw for part in ("probe", "follow", "clarif")):
        return "probe"
    return ""


def _normalize_target_indices(value: Any, expectation_count: int) -> List[int]:
    raw_values: List[Any]
    if isinstance(value, list):
        raw_values = value
    elif isinstance(value, tuple):
        raw_values = list(value)
    elif value is None:
        raw_values = []
    elif isinstance(value, str):
        raw_values = re.findall(r"\d+", value)
    else:
        raw_values = [value]

    indices: List[int] = []
    for raw in raw_values:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if expectation_count > 0:
            idx = max(0, min(idx, expectation_count - 1))
        if idx not in indices:
            indices.append(idx)
    return indices or [0]


def _repair_definition_first_question(text: str) -> str:
    """Rewrite a definition-first opening into a conversational question.

    This preserves the model's content and only changes the opening, so it is
    not a prewritten substitute question.
    """
    lower = text.lower()
    for prefix in (
        "what's the difference between ",
        "what is the difference between ",
        "what are the differences between ",
    ):
        if lower.startswith(prefix):
            return "Could you walk me through the difference between " + text[len(prefix):]
    for prefix in ("what is ", "what are ", "define ", "can you define "):
        if lower.startswith(prefix):
            return "Could you walk me through " + text[len(prefix):]
    return text


def _ground_probe_trigger_conditions(content: SkillSectionContent) -> int:
    """Make probe triggers explicit when a probe names rubric techniques.

    The validator correctly rejects a probe that names a technique the
    candidate has not raised. Rather than repeatedly failing generation for a
    metadata omission, extend the trigger to require that exact mention. The
    probe wording itself is never replaced.
    """
    repairs = 0
    expectations = [e.expectation_text for e in content.expectations]
    for probe in content.probes:
        probe_keywords = extract_keywords(probe.question_text)
        trigger = probe.trigger_condition or ""
        trigger_keywords = extract_keywords(trigger)
        for expectation_text in expectations:
            named = probe_keywords.intersection(extract_keywords(expectation_text))
            untriggered = named - trigger_keywords
            if len(untriggered) >= 2:
                cleaned_trigger = trigger.rstrip(". ")
                if cleaned_trigger:
                    probe.trigger_condition = (
                        f"{cleaned_trigger}, specifically mentioning "
                        f"{' and '.join(sorted(untriggered))}."
                    )
                else:
                    probe.trigger_condition = (
                        "Candidate specifically mentions " + " and ".join(sorted(untriggered)) + "."
                    )
                repairs += 1
                break
    return repairs


def _normalize_question_item(
    item: Any,
    default_role: str = "",
    default_trigger: Optional[str] = None,
    expectation_count: int = 0,
) -> Optional[Dict[str, Any]]:
    if isinstance(item, list):
        for candidate in item:
            normalized = _normalize_question_item(candidate, default_role, default_trigger, expectation_count)
            if normalized and normalized.get("question_text"):
                return normalized
        return None

    if isinstance(item, str):
        text = item.strip()
        role = default_role
        trigger = default_trigger
        indices: Any = [0]
    elif isinstance(item, dict):
        text = _as_clean_text(
            item.get("question_text")
            or item.get("question")
            or item.get("text")
            or item.get("prompt")
            or item.get("wording")
        )
        role = _canonical_question_role(
            item.get("question_role")
            or item.get("role")
            or item.get("kind")
            or item.get("type")
            or default_role
        ) or default_role
        trigger = (
            item.get("trigger_condition")
            or item.get("trigger")
            or item.get("condition")
            or item.get("when")
            or default_trigger
        )
        indices = (
            item.get("target_expectation_indices")
            or item.get("target_expectations")
            or item.get("target_indices")
            or item.get("target_expectation_index")
            or [0]
        )
    else:
        return None

    if not text:
        return None
    text = text.strip()
    if text.endswith("?"):
        text = re.sub(r"\?+$", "?", text)
    else:
        text = re.sub(r"[\.\s]+$", "", text) + "?"
    text = _repair_definition_first_question(text)
    if not text.endswith("?"):
        text = text.rstrip("?") + "?"

    return {
        "question_role": role,
        "question_text": text,
        "trigger_condition": str(trigger).strip() if trigger else None,
        "target_expectation_indices": _normalize_target_indices(indices, expectation_count),
    }


def _extract_expectations(raw_exp: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    if isinstance(raw_exp, dict):
        if any(k in raw_exp for k in ("expectation_text", "text", "description", "expectation")):
            single = _normalize_expectation_item(raw_exp)
            return [single] if single else []
        for group_key, group_value in raw_exp.items():
            level_default = group_key if re.fullmatch(r"l?[1-5]", str(group_key).lower()) else None
            importance_default = None
            if str(group_key).lower() in {"core", "stretch"}:
                importance_default = str(group_key).lower()
            values = group_value if isinstance(group_value, list) else [group_value]
            for value in values:
                normalized = _normalize_expectation_item(
                    value,
                    default_level=level_default,
                    default_importance=importance_default,
                )
                if normalized:
                    items.append(normalized)
        return items

    if isinstance(raw_exp, list):
        for value in raw_exp:
            normalized = _normalize_expectation_item(value)
            if normalized:
                items.append(normalized)
        return items

    normalized = _normalize_expectation_item(raw_exp)
    return [normalized] if normalized else []


def _parse_section_json(raw_data: Any) -> Dict[str, Any]:
    if isinstance(raw_data, SkillSectionContent):
        return raw_data.model_dump()
    if isinstance(raw_data, dict):
        return raw_data
    if not isinstance(raw_data, str):
        raise ValueError(f"Expected a JSON object or string, got {type(raw_data)}")

    cleaned = raw_data.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except Exception:
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"Could not parse JSON from model output: {cleaned[:160]}...")
        parsed = json.loads(match.group(1))

    if not isinstance(parsed, dict):
        raise ValueError("Model output JSON must be an object")
    return parsed


def _normalize_skill_section_payload(
    raw_data: Any,
    fallback_skill_name: str,
    seniority_level: str = "mid",
) -> tuple[Dict[str, Any], List[str]]:
    """Normalize the provider's actual response shape into the canonical payload.

    Providers in this app return either the canonical schema
    (``anchor_question`` / ``importance``) or a compact shape:
      expectations: [{description, level, stretch}]
      questions: [{kind, question}]
      probes: [{kind, question, trigger_condition, target_expectation_indices}]
    Both are parsed. Missing required content is reported, never replaced with
    a prewritten question.
    """
    data = _parse_section_json(raw_data)
    skill_name = _as_clean_text(data.get("skill_name") or data.get("name")) or fallback_skill_name
    errors: List[str] = []

    expectations = _apply_expectation_caps(_extract_expectations(data.get("expectations")))
    if len(expectations) < 2:
        errors.append(
            f"Section '{skill_name}' returned {len(expectations)} usable expectations; at least 2 are required."
        )

    sen_clean = str(seniority_level or "mid").lower()
    is_entry = "entry" in sen_clean
    default_alt_trigger = (
        "Candidate is stuck or unsure where to start"
        if is_entry
        else "Candidate indicates no direct experience with this scenario"
    )

    direct_questions: Dict[str, Any] = {
        "anchor": (
            data.get("anchor_question")
            or data.get("anchor")
            or data.get("main_question")
            or data.get("primary_question")
            or data.get("opening_question")
        ),
        "anchor_alt": (
            data.get("anchor_alt_question")
            or data.get("anchor_alt")
            or data.get("hypothetical_question")
            or data.get("hypothetical")
            or data.get("alternative_question")
        ),
        "escalation": (
            data.get("escalation_question")
            or data.get("escalation")
            or data.get("escalated_question")
            or data.get("deeper_question")
        ),
    }

    extracted_questions: Dict[str, Dict[str, Any]] = {}
    extracted_probes: List[Dict[str, Any]] = []

    def _consider_question(normalized: Optional[Dict[str, Any]], fallback_role: str = "") -> None:
        if not normalized or not normalized.get("question_text"):
            return
        role = normalized.get("question_role") or fallback_role
        if role == "probe":
            extracted_probes.append(normalized)
        elif role in ("anchor", "anchor_alt", "escalation"):
            extracted_questions.setdefault(role, normalized)

    raw_questions = data.get("questions")
    if raw_questions:
        keyed_items: List[tuple[Optional[str], Any]] = []
        if isinstance(raw_questions, dict):
            keyed_items = list(raw_questions.items())
        elif isinstance(raw_questions, list):
            keyed_items = [(None, item) for item in raw_questions]
        else:
            keyed_items = [(None, raw_questions)]

        sequence = ["anchor", "anchor_alt", "escalation"]
        for item_index, (group_key, item) in enumerate(keyed_items):
            group_role = _canonical_question_role(group_key) if group_key else ""
            if group_role == "probe" and isinstance(item, list):
                for probe_item in item:
                    _consider_question(
                        _normalize_question_item(
                            probe_item,
                            default_role="probe",
                            default_trigger="Candidate gives a surface-level response",
                            expectation_count=len(expectations),
                        ),
                        "probe",
                    )
                continue
            item_role = ""
            if isinstance(item, dict):
                item_role = _canonical_question_role(
                    item.get("kind") or item.get("role") or item.get("question_role") or item.get("type")
                )
            fallback_role = item_role or group_role or (sequence[item_index] if item_index < len(sequence) else "probe")
            _consider_question(
                _normalize_question_item(
                    item,
                    default_role=fallback_role,
                    default_trigger=(
                        "Candidate gives a surface-level response" if fallback_role == "probe" else None
                    ),
                    expectation_count=len(expectations),
                ),
                fallback_role,
            )

    for role in ("anchor", "anchor_alt", "escalation"):
        if not extracted_questions.get(role):
            direct = direct_questions.get(role)
            if direct:
                normalized = _normalize_question_item(
                    direct,
                    default_role=role,
                    default_trigger=default_alt_trigger if role == "anchor_alt" else None,
                    expectation_count=len(expectations),
                )
                _consider_question(normalized, role)

    anchor = extracted_questions.get("anchor")
    if not anchor:
        errors.append(f"Section '{skill_name}' is missing the required anchor question.")
    elif not anchor.get("trigger_condition"):
        anchor["trigger_condition"] = None

    anchor_alt = extracted_questions.get("anchor_alt")
    if not anchor_alt:
        errors.append(f"Section '{skill_name}' is missing the required anchor_alt question.")
    else:
        anchor_alt["trigger_condition"] = (
            "Candidate is stuck or unsure where to start"
            if is_entry
            else "Candidate indicates no direct experience with this scenario"
        )

    escalation = extracted_questions.get("escalation")
    if not escalation:
        errors.append(f"Section '{skill_name}' is missing the required escalation question.")

    raw_probes = data.get("probes") or data.get("followup_probes") or data.get("follow_up_questions") or []
    if isinstance(raw_probes, dict):
        probe_values = list(raw_probes.values())
    elif isinstance(raw_probes, list):
        probe_values = raw_probes
    else:
        probe_values = [raw_probes]

    for probe_item in probe_values:
        _consider_question(
            _normalize_question_item(
                probe_item,
                default_role="probe",
                default_trigger="Candidate gives a surface-level response",
                expectation_count=len(expectations),
            ),
            "probe",
        )

    probes: List[Dict[str, Any]] = []
    seen_probe_texts: set[str] = set()
    for probe in extracted_probes:
        if probe.get("question_role") not in ("probe", ""):
            continue
        key = re.sub(r"\s+", " ", probe["question_text"].strip().lower())
        if key in seen_probe_texts:
            continue
        seen_probe_texts.add(key)
        probes.append(probe)

    if len(probes) < 3:
        errors.append(
            f"Section '{skill_name}' returned {len(probes)} unique probes; at least 3 are required."
        )

    payload = {
        "skill_name": skill_name,
        "expectations": expectations,
        "anchor_question": anchor,
        "anchor_alt_question": anchor_alt,
        "escalation_question": escalation,
        "probes": probes[:6],
    }
    return payload, errors


def _normalize_skill_section_data(raw_data: Any, fallback_skill_name: str, seniority_level: str = "mid") -> SkillSectionContent:
    """Normalize model output and raise if required content is missing."""
    if isinstance(raw_data, SkillSectionContent):
        return raw_data

    payload, errors = _normalize_skill_section_payload(raw_data, fallback_skill_name, seniority_level)
    if errors:
        raise SectionContentError(errors, payload)
    content = SkillSectionContent.model_validate(payload)
    _ground_probe_trigger_conditions(content)
    return content


class BlueprintGenerationError(RuntimeError):
    """Raised when blueprint generation fails after all attempts and repair passes."""
    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors or []


import hashlib

_SECTION_CACHE: Dict[str, Dict[str, Any]] = {}
_SECTION_CACHE_MAX_ENTRIES = 256


def compute_section_input_hash(
    job_title: str,
    seniority_level: str,
    skill_info: Dict[str, Any],
    job_description: Optional[str] = None,
) -> str:
    """Compute deterministic SHA256 input hash to cache identical section generations."""
    parts = [
        job_title.strip().lower(),
        seniority_level.strip().lower(),
        (skill_info.get("name") or skill_info.get("skill_name") or "").strip().lower(),
        str(skill_info.get("category", "")).strip().lower(),
        str(skill_info.get("priority_tier", "")).strip().lower(),
        str(skill_info.get("weight_percentage", "")),
        str(skill_info.get("target_level_min", "")),
        str(skill_info.get("target_level_max", "")),
        str(skill_info.get("rubric_l1", "")),
        str(skill_info.get("rubric_l2", "")),
        str(skill_info.get("rubric_l3", "")),
        str(skill_info.get("rubric_l4", "")),
        str(skill_info.get("rubric_l5", "")),
        str(skill_info.get("recommended_expectations", 3)),
        (job_description or "")[:200].strip().lower(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


_GENERIC_OPENING_PREFIXES = [
    "Tell me, ",
    "I'm curious — ",
    "Consider this: ",
]

# First words that are safe to decapitalize when prepending a generic lead-in.
_SAFE_DECAPITALIZE_WORDS = {
    "how", "what", "when", "where", "why", "who", "which", "if", "suppose",
    "imagine", "describe", "explain", "tell", "walk", "give", "have", "could",
    "can", "would", "should", "did", "do", "are", "is", "was", "were",
}


def _decapitalize_first_word(text: str) -> str:
    """Lowercase the leading word only when it is a common question opener."""
    if not text:
        return text
    first, _, rest = text.partition(" ")
    if first.lower().strip("',") in _SAFE_DECAPITALIZE_WORDS:
        return first.lower() + (" " + rest if rest else "")
    return text


def _rewrite_question_opening(orig_text: str, cycle: int) -> str:
    """Rewrite a question opening, preferring grammatical family rules and
    falling back to a generic spoken lead-in. Never returns a question longer
    than 45 words (the hard ceiling enforced elsewhere)."""
    orig_clean = orig_text.strip()
    word_budget = 45
    candidates = [
        _diversify_anchor_text(orig_clean, c)
        for c in range(cycle, cycle + 4)
    ]
    for prefix in _GENERIC_OPENING_PREFIXES:
        if prefix == "Consider this: ":
            candidates.append(prefix + orig_clean)
        else:
            candidates.append(prefix + _decapitalize_first_word(orig_clean))
    seen: set = set()
    for cand in candidates:
        cand = cand.strip()
        if not cand or cand == orig_clean or cand in seen:
            continue
        seen.add(cand)
        # Normalize to exactly one trailing '?'
        cand = re.sub(r"[\.,;:!?\s]+$", "", cand)
        cand = re.sub(r"\?+", "?", cand) + "?"
        if len(cand.split()) <= word_budget:
            return cand
    return orig_clean


def _diversify_anchor_text(orig_text: str, cycle: int) -> str:
    """Grammatically replace repetitive anchor openings preserving verb and noun structure."""
    orig_clean = orig_text.strip()
    # 0a. "how would you"
    if re.search(r"^how would you\s+", orig_clean, flags=re.IGNORECASE):
        variants = [
            "Walk me through how you would ",
            "Could you explain how you would ",
            "Describe how you would ",
            "I'm curious — how would you ",
        ]
        var = variants[cycle % len(variants)]
        return re.sub(r"^how would you\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 0b. "how do you"
    if re.search(r"^how do you\s+", orig_clean, flags=re.IGNORECASE):
        variants = [
            "Tell me, how do you ",
            "Could you explain how you ",
            "Walk me through how you ",
        ]
        var = variants[cycle % len(variants)]
        return re.sub(r"^how do you\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 0c. "how did you" / "how have you"
    m_how_past = re.match(r"^how (did|have) you\s+(\S.*)$", orig_clean, flags=re.IGNORECASE)
    if m_how_past:
        tense = m_how_past.group(1).lower()
        if tense == "have":
            variants = ["Tell me, how have you ", "I'm curious — how have you ", "Could you describe how you "]
        else:
            variants = ["Tell me, how did you ", "I'm curious — how did you ", "Could you share how you "]
        var = variants[cycle % len(variants)]
        return var + m_how_past.group(2)
    # 0d. "what is your" / "what are your"
    if re.search(r"^what (is|are) your\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Tell me about your ", "Describe your ", "Could you share your "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^what (is|are) your\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 0e. "what are the" / "what is the"
    if re.search(r"^what (is|are) the\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Tell me about the ", "Could you explain the ", "Walk me through the "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^what (is|are) the\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 0f. "what would you"
    if re.search(r"^what would you\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Tell me, what would you ", "Walk me through what you would ", "I'm curious — what would you "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^what would you\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 0g. "describe how you" / "explain how you" / "tell me how"
    if re.search(r"^(describe|explain) how you\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Tell me how you ", "Could you describe how you ", "Walk me through how you "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^(describe|explain) how you\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    if re.search(r"^tell me how\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Could you explain how ", "Walk me through how ", "Describe for me how "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^tell me how\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 0h. "give me an example of" / "give an example of"
    if re.search(r"^give (me )?an example of\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Could you share an example of ", "Tell me about one time ", "I'm curious about an example of "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^give (me )?an example of\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 0i. "have you ever"
    if re.search(r"^have you ever\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Tell me about a time you ", "I'm curious whether you have ever ", "Could you describe an occasion you "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^have you ever\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 0j. "if you were"
    if re.search(r"^if you were\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Imagine you were ", "Suppose you were ", "Say you were "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^if you were\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 1. "walk me through a/an"
    if re.search(r"^walk me through an?\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Could you describe ", "Tell me about ", "Could you share details on "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^walk me through\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 2. "walk me through how you"
    if re.search(r"^walk me through how you\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Could you discuss how you ", "Could you explain how you ", "Could you describe how you "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^walk me through how you\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 3. "walk me through your"
    if re.search(r"^walk me through your\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Could you discuss your ", "Describe your ", "Could you take me through your "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^walk me through your\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 4. "can you walk me through"
    if re.search(r"^can you walk me through\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Could you explain ", "Could you discuss ", "Could you describe "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^can you walk me through\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 5. "tell me about a/an"
    if re.search(r"^tell me about an?\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Could you walk me through ", "Could you describe "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^tell me about\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 6. Generic "walk me through"
    if re.search(r"^walk me through\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Could you describe ", "Could you discuss ", "Could you explain "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^walk me through\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 7. "suppose you are"
    if re.search(r"^suppose you are\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Imagine you are ", "Consider a scenario where you are ", "Say you are tasked with being "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^suppose you are\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 8. "suppose you receive"
    if re.search(r"^suppose you receive\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Imagine you receive ", "Consider a case where you receive ", "Say you receive "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^suppose you receive\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 9. "suppose you have"
    if re.search(r"^suppose you have\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Imagine you have ", "Consider a setup where you have ", "Say you have "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^suppose you have\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 10. "suppose you need"
    if re.search(r"^suppose you need\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Imagine you need ", "Consider a scenario where you need ", "Say you need "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^suppose you need\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 11. Generic "suppose you"
    if re.search(r"^suppose you\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Imagine you ", "Consider a scenario where you ", "Say you "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^suppose you\s+", var, orig_clean, count=1, flags=re.IGNORECASE)
    # 12. Generic "suppose"
    if re.search(r"^suppose\s+", orig_clean, flags=re.IGNORECASE):
        variants = ["Imagine ", "Consider if ", "Say "]
        var = variants[cycle % len(variants)]
        return re.sub(r"^suppose\s+", var, orig_clean, count=1, flags=re.IGNORECASE)

    return orig_clean


def auto_repair_blueprint_questions(sections: List[Dict[str, Any]]) -> int:
    """Deterministically auto-repair:
    1. Trailing punctuation: ensure every question ends with a single '?' without trailing dots/spaces/multiple marks.
    2. Verbose preamble trimming: trim redundant verbal filler if word count > 38.
    3. Duplicate escalation / repeated probe repair.
    4. Opening variety across ALL questions (anchors, anchor_alt, escalation, probes):
       if more than 35% of questions (min 4) share the same 3-word opening — the exact
       condition the validator warns on — diversify the surplus questions so the
       blueprint no longer trips validate_blueprint's 'questions.variety' warning.
    Returns count of repaired items.
    """
    repairs_count = 0

    # 1. Punctuation repair and verbose filler trimming
    for s in sections:
        if s.get("section_type") != "skill":
            continue
        content = s.get("content")
        if not content:
            continue

        def _clean_q(q_obj):
            nonlocal repairs_count
            if not q_obj or not getattr(q_obj, "question_text", None):
                return
            orig = q_obj.question_text.strip()
            cleaned = orig
            # Strip backticks: `foo` -> foo
            cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
            # Strip bold/italic asterisks: **foo** -> foo
            cleaned = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", cleaned)
            # Strip leading bullets
            cleaned = re.sub(r"^[-*•]\s+", "", cleaned)
            # If word count > 35, trim common redundant conversational filler
            if len(cleaned.split()) > 35:
                for pat, rep in [
                    (r"\bwalk me through in detail how you\b", "walk me through how you"),
                    (r"\bcan you talk me through in detail\b", "can you talk me through"),
                    (r"\bcould you please walk me through\b", "could you walk me through"),
                    (r"\bcould you please describe\b", "could you describe"),
                    (r"\btalk me through step by step how you would\b", "talk me through how you would"),
                    (r"\bin a production scenario where you are\b", "suppose you are"),
                    (r"\bin a scenario where you are\b", "suppose you are"),
                    (r"\bin this specific scenario, how would you\b", "how would you"),
                    (r"\bin this scenario, how would you\b", "how would you"),
                    (r"\bwhat specific considerations and trade-offs\b", "what trade-offs"),
                    (r"\bwhat specific architectural considerations\b", "what considerations"),
                    (r"\bhow would you go about designing\b", "how would you design"),
                    (r"\bhow would you go about implementing\b", "how would you implement"),
                    (r"\bhow would you go about\b", "how would you"),
                    (r"\bcan you walk me through how you would\b", "how would you"),
                    (r"\bcould you walk me through how you would\b", "how would you"),
                    (r"\bwalk me through how you would\b", "how would you"),
                    (r"\bfrom your perspective, how would you\b", "how would you"),
                    (r"\bfrom your perspective, what are\b", "what are"),
                    (r"\bin terms of performance, latency, and scalability\b", "for performance and scale"),
                    (r"\bin terms of performance and scalability\b", "for performance and scale"),
                ]:
                    cleaned = re.sub(pat, rep, cleaned, flags=re.IGNORECASE)
                if len(cleaned.split()) > 38:
                    cleaned = re.sub(r",\s*(specifically|particularly|especially)\s+considering[^?]+", "", cleaned, flags=re.IGNORECASE)
            # Clean trailing punctuation to ensure exactly one '?'
            cleaned = re.sub(r"[\.,;:!?\s]+$", "", cleaned)
            cleaned = re.sub(r"\?+", "?", cleaned) + "?"
            if cleaned != orig:
                q_obj.question_text = cleaned
                repairs_count += 1

        _clean_q(getattr(content, "anchor_question", None))
        _clean_q(getattr(content, "anchor_alt_question", None))
        _clean_q(getattr(content, "escalation_question", None))
        for p in getattr(content, "probes", []):
            _clean_q(p)

    # 2. Probe technique leakage repair
    from backend.app.services.blueprint.validator import extract_keywords
    for s in sections:
        if s.get("section_type") != "skill":
            continue
        content = s.get("content")
        if not content:
            continue
        exps = [e.expectation_text for e in getattr(content, "expectations", [])]
        for p in getattr(content, "probes", []):
            if not getattr(p, "question_text", None):
                continue
            probe_kws = extract_keywords(p.question_text)
            trig = getattr(p, "trigger_condition", "") or ""
            trig_kws = extract_keywords(trig)
            for exp_text in exps:
                exp_kws = extract_keywords(exp_text)
                named = probe_kws.intersection(exp_kws)
                untriggered = named - trig_kws
                if len(untriggered) >= 2:
                    cleaned_trig = trig.rstrip(". ")
                    p.trigger_condition = f"{cleaned_trig}, specifically mentioning {' and '.join(sorted(untriggered))}."
                    repairs_count += 1
                    logger.info("Auto-repaired probe trigger condition to ground techniques: %s", untriggered)
                    break

    # 3. Auto-repair duplicate escalations and repeated probes
    for s in sections:
        if s.get("section_type") != "skill":
            continue
        content = s.get("content")
        if not content:
            continue
        s_name = s.get("skill_name") or s.get("title") or "this system"

        # Check anchor vs escalation duplication
        anchor_q = getattr(content, "anchor_question", None)
        esc_q = getattr(content, "escalation_question", None)
        if anchor_q and esc_q and getattr(anchor_q, "question_text", None) and getattr(esc_q, "question_text", None):
            a_txt = anchor_q.question_text.strip().lower()
            e_txt = esc_q.question_text.strip().lower()
            if a_txt == e_txt or ("how do you handle" in e_txt and "challenges in" in e_txt):
                esc_q.question_text = f"If transaction volume spikes by 10x or network partitions occur in {s_name}, what failure modes emerge, and how would you preserve availability?"
                repairs_count += 1

        # Check duplicate probes within the section
        probes = getattr(content, "probes", []) or []
        seen_probes = set()
        fallback_probe_pool = [
            f"What primary constraints shaped your architecture decisions for {s_name}?",
            f"How would you verify correctness and handle subtle boundary or failure conditions in {s_name}?",
            f"If this component became a bottleneck, what profiling signals would guide your optimization?",
            f"How would you ensure backward compatibility and safe rollback during a production deploy?",
        ]
        fb_i = 0
        for p in probes:
            ptxt = getattr(p, "question_text", "").strip()
            if not ptxt or ptxt.lower() in seen_probes:
                while fb_i < len(fallback_probe_pool) and fallback_probe_pool[fb_i].lower() in seen_probes:
                    fb_i += 1
                if fb_i < len(fallback_probe_pool):
                    p.question_text = fallback_probe_pool[fb_i]
                    seen_probes.add(fallback_probe_pool[fb_i].lower())
                    fb_i += 1
                    repairs_count += 1
            else:
                seen_probes.add(ptxt.lower())

    # 4. Cross-section question opening variety (mirrors validator rule: >35% share, >=4 questions)
    repairs_count += repair_blueprint_opening_variety(sections)

    return repairs_count


_VARIETY_ROLE_RANK = {"probe": 0, "anchor_alt": 1, "escalation": 2, "anchor": 3}


def _collect_blueprint_question_items(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect every skill-section question (both the in-memory `content` shape used
    during generation and the serialized `questions`-dict shape used on update/regenerate)
    so opening-variety repair can reason across the whole blueprint exactly like
    validate_blueprint does."""
    items: List[Dict[str, Any]] = []
    for s_idx, s in enumerate(sections):
        if s.get("section_type") != "skill":
            continue
        content = s.get("content")
        if content is not None and not isinstance(content, dict):
            for role in ("anchor", "anchor_alt", "escalation"):
                q = getattr(content, f"{role}_question", None)
                if q is not None and getattr(q, "question_text", None):
                    items.append({"obj": q, "role": role, "sec": s_idx, "is_dict": False})
            for p in getattr(content, "probes", []) or []:
                if getattr(p, "question_text", None):
                    items.append({"obj": p, "role": "probe", "sec": s_idx, "is_dict": False})
        else:
            for q in s.get("questions") or []:
                if isinstance(q, dict) and q.get("question_text"):
                    items.append({
                        "obj": q,
                        "role": str(q.get("question_role") or "probe"),
                        "sec": s_idx,
                        "is_dict": True,
                    })
    return items


def _question_item_text(item: Dict[str, Any]) -> str:
    if item["is_dict"]:
        return str(item["obj"].get("question_text") or "")
    return str(getattr(item["obj"], "question_text") or "")


def _set_question_item_text(item: Dict[str, Any], new_text: str) -> None:
    if item["is_dict"]:
        item["obj"]["question_text"] = new_text
    else:
        item["obj"].question_text = new_text


def repair_blueprint_opening_variety(sections: List[Dict[str, Any]], max_passes: int = 4) -> int:
    """Diversify over-represented question openings so the blueprint satisfies
    validate_blueprint's variety guideline (<=35% of questions sharing the same
    first three words). Deterministic, grammar-preserving, and word-budget aware;
    rewrites probes before anchor questions and later sections before earlier ones.
    Handles both the generation-time `content` shape and the serialized
    `questions`-dict shape. Returns the number of questions rewritten."""
    items = _collect_blueprint_question_items(sections)
    total = len(items)
    if total < 5:
        return 0

    max_allowed = int(0.35 * total)
    repaired = 0
    cycle = 0

    for _pass in range(max_passes):
        openings: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            text = _question_item_text(it)
            pref = " ".join(text.strip().lower().split()[:3])
            it["pref"] = pref
            openings.setdefault(pref, []).append(it)

        targets = [
            (pref, members)
            for pref, members in openings.items()
            if len(members) >= 4 and len(members) / total > 0.35
        ]
        if not targets:
            return repaired

        targets.sort(key=lambda kv: -len(kv[1]))
        for pref, members in targets:
            need = len(members) - max_allowed
            if need <= 0:
                continue
            # Rewrite the most dispensable questions first: probes, then anchor_alt,
            # escalation, and anchors last; within a role prefer later (lower-priority) sections.
            victims = sorted(
                members,
                key=lambda it: (_VARIETY_ROLE_RANK.get(it["role"], 0), -it["sec"]),
            )
            for it in victims[:need]:
                old_text = _question_item_text(it)
                new_text = _rewrite_question_opening(old_text, cycle)
                cycle += 1
                if new_text and new_text != old_text:
                    _set_question_item_text(it, new_text)
                    repaired += 1

    remaining = 0
    openings = {}
    for it in items:
        pref = " ".join(_question_item_text(it).strip().lower().split()[:3])
        openings[pref] = openings.get(pref, 0) + 1
    remaining = sum(c for c in openings.values() if c >= 4 and c / total > 0.35)
    if remaining:
        logger.warning(
            "Opening variety repair left %d questions in over-represented openings after %d passes",
            remaining, max_passes,
        )
    return repaired


def _get_target_models() -> List[str]:
    primary = os.getenv("GEMINI_MODEL_PLAN", "gemini-3.5-flash")
    fallbacks = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    candidates = [primary] + [f for f in fallbacks if f != primary]
    return candidates


def _generate_single_skill_sync(
    job_title: str,
    seniority_level: str,
    skill_info: Dict[str, Any],
    section_index: int,
    job_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Synchronously generate and validate a single skill section with caching and router failover."""
    from backend.app.services.llm_router import (
        is_fatal_auth_error,
        extract_retry_after,
        get_backup_api_key,
        call_backup_chat_sync,
        GEMINI_CIRCUIT_BREAKER,
        GEMINI_KEY_MANAGER,
        rotate_gemini_key,
        ProviderAuthError,
    )

    s_name = skill_info.get("skill_name") or skill_info.get("name") or "Skill"

    # Input hash caching
    cache_key = compute_section_input_hash(job_title, seniority_level, skill_info, job_description)
    if cache_key in _SECTION_CACHE:
        cached = _SECTION_CACHE[cache_key]
        logger.info("Cache HIT for section '%s' (hash: %s...)", s_name, cache_key[:8])
        return {
            "content": cached["content"].model_copy(deep=True),
            "model_used": cached["model_used"],
            "cached": True,
        }

    target_models = _get_target_models()
    prompt = build_skill_section_user_prompt(
        job_title=job_title,
        seniority_level=seniority_level,
        skill_info=skill_info,
        job_description=job_description,
        recommended_expectations=skill_info.get("recommended_expectations", 3),
    )

    last_exc = None
    raw_output: Optional[str] = None
    model_used: Optional[str] = None
    client = None

    # Circuit breaker check: Only attempt Gemini if CLOSED or HALF-OPEN
    if GEMINI_CIRCUIT_BREAKER.can_attempt():
        total_keys = max(GEMINI_KEY_MANAGER.key_count, 1)
        for key_attempt in range(total_keys):
            try:
                client = get_gemini_client()
            except Exception as exc:
                client = None
                last_exc = exc
                if is_fatal_auth_error(exc):
                    raise ProviderAuthError(f"Fatal Gemini authentication error: {exc}")
                GEMINI_CIRCUIT_BREAKER.record_failure(str(exc))
                break

            if not client:
                break

            key_failed = False
            for model_name in target_models:
                try:
                    t0 = time.perf_counter()
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SKILL_SECTION_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            response_schema=SkillSectionContent,
                            max_output_tokens=2048,
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                            http_options=types.HttpOptions(timeout=25000, retry_options=types.HttpRetryOptions(attempts=1)),
                        ),
                    )
                    dur = (time.perf_counter() - t0) * 1000.0
                    raw_output = response.text
                    model_used = model_name
                    GEMINI_CIRCUIT_BREAKER.record_success()
                    logger.info("Generated raw section for '%s' using %s in %.1fms", s_name, model_name, dur)
                    break
                except Exception as exc:
                    last_exc = exc
                    err_str = str(exc)
                    if is_fatal_auth_error(exc):
                        logger.error("Fatal Gemini authentication error on key: %s", err_str[:120])
                        rotate_gemini_key(f"Fatal auth error: {err_str[:60]}")
                        key_failed = True
                        break
                    if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "UNAVAILABLE" in err_str or "503" in err_str:
                        logger.warning("Gemini key hit rate limit/unavailable on skill '%s' (%s). Rotating key...", s_name, err_str[:80])
                        rotate_gemini_key(f"Rate-limit / 503 on skill {s_name}")
                        key_failed = True
                        break
                    logger.warning("Gemini error on %s for '%s': %s", model_name, s_name, err_str[:120])
                    break

            if raw_output:
                break
            if not key_failed:
                break
    else:
        logger.info("Gemini circuit breaker is OPEN, routing '%s' directly to backup provider", s_name)

    # Secondary provider fallback (OpenRouter / NVIDIA)
    if not raw_output and get_backup_api_key():
        logger.info("Routing section for '%s' to secondary backup provider (OpenRouter/NVIDIA)", s_name)
        try:
            messages = [
                {"role": "system", "content": SKILL_SECTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            raw_output, bk_model = call_backup_chat_sync(messages=messages, json_mode=True, timeout=60.0)
            model_used = bk_model
            logger.info("Generated raw section for '%s' using backup provider (%s)", s_name, bk_model)
        except Exception as bk_exc:
            last_exc = f"Gemini error: {last_exc}; Backup error: {bk_exc}"

    if not raw_output:
        raise BlueprintGenerationError(
            f"Failed to generate section for skill '{skill_info.get('name')}': {last_exc}"
        )

    def _normalize_and_validate(raw_text: str) -> tuple[Optional[SkillSectionContent], List[str], Dict[str, Any]]:
        try:
            payload, normalization_errors = _normalize_skill_section_payload(
                raw_text,
                s_name,
                seniority_level=seniority_level,
            )
        except Exception as parse_exc:
            return None, [f"Could not parse section output: {parse_exc}"], {"raw_output": raw_text}
        if normalization_errors:
            return None, normalization_errors, payload

        try:
            content = SkillSectionContent.model_validate(payload)
        except Exception as schema_exc:
            return None, [f"Section schema validation failed: {schema_exc}"], payload

        _ground_probe_trigger_conditions(content)

        section_issues = validate_skill_section(
            section=content,
            allocated_minutes=skill_info.get("allocated_minutes", 4.0),
            section_index=section_index,
            seniority_level=seniority_level,
        )
        section_errors = [i.message for i in section_issues if i.severity == "error"]
        return content, section_errors, payload

    def _request_repair(draft_payload: Dict[str, Any], validation_errors: List[str]) -> tuple[Optional[str], Optional[str]]:
        repair_prompt = build_repair_user_prompt(
            original_draft=draft_payload,
            validation_errors=validation_errors,
        )
        used_backup = bool(
            model_used
            and ("openrouter" in model_used.lower() or "nvidia" in model_used.lower() or "backup" in model_used.lower())
        )

        if not used_backup and client is not None:
            try:
                repaired_response = client.models.generate_content(
                    model=model_used or target_models[0],
                    contents=repair_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SKILL_SECTION_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=SkillSectionContent,
                        max_output_tokens=2048,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                        http_options=types.HttpOptions(timeout=25000, retry_options=types.HttpRetryOptions(attempts=1)),
                    ),
                )
                return repaired_response.text, model_used
            except Exception as repair_exc:
                logger.warning("Gemini repair pass failed for '%s': %s", s_name, repair_exc)

        if get_backup_api_key():
            try:
                rep_messages = [
                    {"role": "system", "content": SKILL_SECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ]
                repaired_raw, repair_model = call_backup_chat_sync(
                    messages=rep_messages,
                    json_mode=True,
                    timeout=60.0,
                )
                return repaired_raw, repair_model
            except Exception as backup_repair_exc:
                logger.warning("Backup repair pass failed for '%s': %s", s_name, backup_repair_exc)

        return None, None

    section_content, section_errors, draft_payload = _normalize_and_validate(raw_output)

    # Up to three targeted repairs. Never keep an invalid/generic section:
    # fail loudly if the provider cannot deliver.
    for repair_attempt in range(3):
        if section_content is not None and not section_errors:
            break
        logger.warning(
            "Section '%s' needs repair (attempt %d): %s",
            s_name,
            repair_attempt + 1,
            section_errors,
        )
        repaired_raw, repaired_model = _request_repair(draft_payload or {}, section_errors)
        if not repaired_raw:
            break
        if repaired_model:
            model_used = repaired_model
        section_content, section_errors, draft_payload = _normalize_and_validate(repaired_raw)

    if section_content is None or section_errors:
        raise BlueprintGenerationError(
            f"Section generation failed for '{s_name}' after repair",
            errors=section_errors or ["Section output remained incomplete after repair"],
        )

    logger.info("Section '%s' passed deterministic validation", s_name)

    if len(_SECTION_CACHE) >= _SECTION_CACHE_MAX_ENTRIES:
        # FIFO eviction: drop the oldest inserted entries to keep memory bounded
        for stale_key in list(_SECTION_CACHE.keys())[: len(_SECTION_CACHE) - _SECTION_CACHE_MAX_ENTRIES + 1]:
            del _SECTION_CACHE[stale_key]
    _SECTION_CACHE[cache_key] = {
        "content": section_content,
        "model_used": model_used,
    }

    return {
        "content": section_content,
        "model_used": model_used,
    }


async def generate_single_skill_section(
    job_title: str,
    seniority_level: str,
    skill_info: Dict[str, Any],
    section_index: int = 1,
    job_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Asynchronously generate or regenerate a single skill section."""
    return await asyncio.to_thread(
        _generate_single_skill_sync,
        job_title=job_title,
        seniority_level=seniority_level,
        skill_info=skill_info,
        section_index=section_index,
        job_description=job_description,
    )


async def generate_job_blueprint(
    job_id: str,
    job_title: str,
    seniority_level: str,
    duration_mins: int,
    skills: List[Dict[str, Any]],
    job_description: Optional[str] = None,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Generate a complete, validated Job Interview Blueprint across all sections.

    Enforces:
    - Welcome (1.5m), Intro (2.0m), Candidate Q&A (2.0m), Closing (0.5m)
    - Skill sections ordered P0 -> P1 -> P2
    - Every P0 skill MUST have a section
    - Voice writing rules (max ~35 words, 1 question mark, scenario-first, no leakage)
    - Concurrency bounded to 3 parallel section generations
    - Batched LLM review quality check
    - Auto-repair of anchor variety (>40%) and punctuation
    - Detailed per-stage timing breakdown and provider tracking
    - NO silent fallback on auth errors
    """
    t_start = time.perf_counter()
    if progress_callback:
        progress_callback("budgeting", 0.05, None)

    # 1. Budgeting
    t_b0 = time.perf_counter()
    budget = calculate_blueprint_section_budgets(duration_mins, skills, seniority_level=seniority_level)
    sections_plan = budget["sections"]
    active_skill_mins = budget["active_skill_mins"]
    budgeting_ms = (time.perf_counter() - t_b0) * 1000.0

    # 2. Concurrently generate content for all skill sections with bounded concurrency
    t_sec0 = time.perf_counter()
    if progress_callback:
        progress_callback("generating_sections", 0.15, None)

    skill_sections_to_gen = [
        (idx, s) for idx, s in enumerate(sections_plan)
        if s.get("section_type") == "skill"
    ]
    sem = asyncio.Semaphore(3)
    completed_count = 0
    total_skill_count = len(skill_sections_to_gen)

    async def _gen_bounded(idx: int, sec_meta: Dict[str, Any]):
        nonlocal completed_count
        async with sem:
            res = await asyncio.to_thread(
                _generate_single_skill_sync,
                job_title=job_title,
                seniority_level=seniority_level,
                skill_info=sec_meta,
                section_index=idx,
                job_description=job_description,
            )
            completed_count += 1
            if progress_callback:
                prog = 0.15 + (0.50 * (completed_count / max(1, total_skill_count)))
                progress_callback(
                    "generating_sections",
                    round(prog, 2),
                    {
                        "skill_name": sec_meta.get("name") or sec_meta.get("skill_name"),
                        "status": "completed",
                        "model": res.get("model_used"),
                    }
                )
            return res

    tasks = [_gen_bounded(idx, s) for idx, s in skill_sections_to_gen]
    try:
        results = await asyncio.gather(*tasks)
    except Exception as exc:
        logger.error("Blueprint generation failed: %s", exc)
        raise BlueprintGenerationError(f"Blueprint generation failed: {exc}")

    section_calls_ms = (time.perf_counter() - t_sec0) * 1000.0

    # Map results back to sections
    for (idx, sec_meta), res in zip(skill_sections_to_gen, results):
        sec_meta["content"] = res["content"]
        sec_meta["model_used"] = res["model_used"]

    # Populate fixed welcome and closing scripts
    for s in sections_plan:
        if s.get("section_type") == "welcome":
            s["welcome_script"] = build_welcome_script(job_title, duration_mins)
        elif s.get("section_type") == "closing":
            s["closing_script"] = build_closing_script(job_title)

    # 3. Deterministic Auto-Repair Pass
    t_rep0 = time.perf_counter()
    if progress_callback:
        progress_callback("repair_passes", 0.70, None)
    repairs_done = auto_repair_blueprint_questions(sections_plan)
    repair_passes_ms = (time.perf_counter() - t_rep0) * 1000.0
    if repairs_done > 0:
        logger.info("Auto-repaired %d question issues (variety/punctuation)", repairs_done)

    # 4. Batched LLM Review Quality Check
    t_llm0 = time.perf_counter()
    if progress_callback:
        progress_callback("batched_llm_review", 0.85, None)
    from backend.app.services.blueprint.validator import run_batched_blueprint_llm_review
    llm_review = await run_batched_blueprint_llm_review(
        sections=sections_plan,
        seniority_level=seniority_level,
        job_title=job_title,
    )
    llm_review_ms = (time.perf_counter() - t_llm0) * 1000.0

    # 5. Comprehensive Blueprint Validation
    validation_report = validate_blueprint(
        sections=sections_plan,
        job_skills=skills,
        active_skill_time=active_skill_mins,
        total_duration_mins=duration_mins,
        seniority_level=seniority_level,
        llm_review=llm_review,
    )

    if not validation_report.is_valid:
        logger.warning("Generated blueprint draft has %d validation errors: %s", len(validation_report.errors), validation_report.errors)

    # 6. Provider and Model Tracking
    used_models = [s.get("model_used") for s in sections_plan if s.get("model_used")]
    has_backup = any(("openrouter" in str(m).lower() or "nvidia" in str(m).lower() or "backup" in str(m).lower()) for m in used_models)
    all_backup = all(("openrouter" in str(m).lower() or "nvidia" in str(m).lower() or "backup" in str(m).lower()) for m in used_models) if used_models else False

    primary_plan_model = os.getenv("GEMINI_MODEL_PLAN", "gemini-3.5-flash-lite")
    from backend.app.services.llm_router import BACKUP_MODEL_PLAN
    if has_backup:
        provider = "backup" if all_backup else "hybrid"
        model_name = BACKUP_MODEL_PLAN
    else:
        provider = "gemini"
        model_name = primary_plan_model

    # Backup Provider Quality & Approval Gate (R3.1 Requirement 2)
    has_errors = bool(validation_report.errors)
    if has_backup and has_errors:
        backup_badge = "generated with backup; regenerate on primary"
        can_be_approved = False
    elif has_backup:
        backup_badge = "generated with backup provider"
        can_be_approved = True
    else:
        backup_badge = None
        can_be_approved = not has_errors

    t_total = (time.perf_counter() - t_start) * 1000.0
    stage_timings = {
        "budgeting_ms": round(budgeting_ms, 1),
        "section_calls_ms": round(section_calls_ms, 1),
        "repair_passes_ms": round(repair_passes_ms, 1),
        "llm_review_ms": round(llm_review_ms, 1),
        "failover_ms": 0.0,
        "total_ms": round(t_total, 1),
    }

    logger.info(
        "Blueprint generated in %.1fms (provider: %s, model: %s, backup: %s, stages: %s)",
        t_total, provider, model_name, has_backup, stage_timings
    )

    if progress_callback:
        progress_callback("finalizing", 1.0, None)

    return {
        "job_id": job_id,
        "total_duration_mins": duration_mins,
        "active_skill_mins": active_skill_mins,
        "fixed_overhead_mins": budget["fixed_overhead_mins"],
        "sections": sections_plan,
        "validation_report": validation_report.model_dump(),
        "budget_warnings": budget["warnings"],
        "dropped_skills": budget["dropped_skills"],
        "generation_provider": provider,
        "generation_model": model_name,
        "generation_latency_ms": round(t_total, 1),
        "generation_stages_ms": stage_timings,
        "is_generated_with_backup": has_backup,
        "backup_badge": backup_badge,
        "can_be_approved": can_be_approved,
    }



def _suggest_skills_sync(
    job_title: str,
    department: str,
    seniority_level: str,
    job_description: str,
) -> List[Dict[str, Any]]:
    from backend.app.services.blueprint.prompts import SUGGEST_SKILLS_SYSTEM_PROMPT
    from backend.app.services.blueprint.contracts import SuggestedSkillsResponse

    prompt = (
        f"Role: {job_title}\n"
        f"Department: {department}\n"
        f"Seniority Level: {seniority_level}\n\n"
        f"Job Description / Scope:\n{job_description or 'Standard production engineering scope for ' + job_title}\n\n"
        "Propose 3 to 4 specific technical evaluation competencies with 5-level rubrics. Weights must sum to 100."
    )

    resp_obj: Optional[SuggestedSkillsResponse] = None
    client = None
    try:
        client = get_gemini_client()
    except Exception:
        pass

    if client:
        target_models = _get_target_models()
        for m in target_models:
            try:
                res = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SUGGEST_SKILLS_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=SuggestedSkillsResponse,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
                resp_obj = SuggestedSkillsResponse.model_validate_json(res.text)
                if resp_obj and resp_obj.skills:
                    break
            except Exception as exc:
                logger.warning("Suggest skills failed on %s: %s", m, exc)

    if not resp_obj or not resp_obj.skills:
        from backend.app.services.llm_router import get_backup_api_key, call_backup_chat_sync
        if get_backup_api_key():
            messages = [
                {"role": "system", "content": SUGGEST_SKILLS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            content, _ = call_backup_chat_sync(messages=messages, json_mode=True, timeout=45.0)
            resp_obj = SuggestedSkillsResponse.model_validate_json(content)

    if not resp_obj or not resp_obj.skills:
        raise RuntimeError("Failed to suggest skills from JD with available AI providers")

    skills_list = [s.model_dump() for s in resp_obj.skills]

    # Normalize weights so they sum to exactly 100%
    total_w = sum(s.get("weight_percentage", 0) for s in skills_list)
    if total_w != 100 and skills_list:
        diff = 100 - total_w
        skills_list[0]["weight_percentage"] += diff

    return skills_list


async def suggest_skills_from_jd(
    job_title: str,
    department: str = "Engineering",
    seniority_level: str = "Mid-Level (L4)",
    job_description: str = "",
) -> List[Dict[str, Any]]:
    """Asynchronously propose calibrated competencies and rubrics from JD."""
    return await asyncio.to_thread(
        _suggest_skills_sync,
        job_title=job_title,
        department=department,
        seniority_level=seniority_level,
        job_description=job_description,
    )

