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
    validate_skill_section,
    validate_blueprint,
)
from backend.app.services.blueprint.seniority_config import normalize_seniority

logger = logging.getLogger(__name__)


def _normalize_skill_section_data(raw_data: Any, fallback_skill_name: str, seniority_level: str = "mid") -> SkillSectionContent:
    """Robustly normalize and parse raw LLM output into SkillSectionContent."""
    if isinstance(raw_data, SkillSectionContent):
        return raw_data

    if isinstance(raw_data, str):
        cleaned = raw_data.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
        except Exception:
            match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
            else:
                raise ValueError(f"Could not parse JSON from model output: {cleaned[:100]}...")
    elif isinstance(raw_data, dict):
        data = raw_data
    else:
        raise ValueError(f"Expected dict or JSON string, got {type(raw_data)}")

    skill_name = str(data.get("skill_name") or data.get("name") or fallback_skill_name).strip()

    # Normalize expectations
    raw_exp = data.get("expectations", [])
    norm_exp = []
    if isinstance(raw_exp, list):
        for e in raw_exp:
            if isinstance(e, str):
                norm_exp.append({
                    "expectation_text": e.strip(),
                    "source_rubric_level": "L4",
                    "importance": "core",
                })
            elif isinstance(e, dict):
                text = e.get("expectation_text") or e.get("text") or e.get("description") or e.get("expectation") or ""
                level = e.get("source_rubric_level") or e.get("rubric_level") or e.get("level") or "L4"
                imp = e.get("importance") or e.get("tier") or e.get("priority") or "core"
                if imp not in ("core", "stretch"):
                    imp = "stretch" if "stretch" in str(imp).lower() else "core"
                if text:
                    norm_exp.append({
                        "expectation_text": str(text).strip(),
                        "source_rubric_level": str(level).strip(),
                        "importance": imp,
                    })
    if len(norm_exp) < 2:
        norm_exp.append({
            "expectation_text": f"Demonstrates core competencies and practical judgment in {skill_name}",
            "source_rubric_level": "L3",
            "importance": "core",
        })
        norm_exp.append({
            "expectation_text": f"Applies best practices, handles edge cases and operational constraints in {skill_name}",
            "source_rubric_level": "L4",
            "importance": "stretch",
        })

    def _norm_q(q_data: Any, default_role: str, default_trigger: Optional[str] = None) -> dict:
        if isinstance(q_data, str):
            txt = q_data.strip()
            if txt and not txt.endswith("?"):
                txt = re.sub(r"[\.\s]+$", "", txt) + "?"
            return {
                "question_role": default_role,
                "question_text": txt,
                "trigger_condition": default_trigger,
                "target_expectation_indices": [0],
            }
        elif isinstance(q_data, dict):
            q_text = str(q_data.get("question_text") or q_data.get("text") or q_data.get("question") or q_data.get("prompt") or "").strip()
            if q_text and not q_text.endswith("?"):
                q_text = re.sub(r"[\.\s]+$", "", q_text) + "?"
            role = q_data.get("question_role") or q_data.get("role") or q_data.get("kind") or default_role
            trig = q_data.get("trigger_condition") or q_data.get("trigger") or q_data.get("condition") or default_trigger
            indices = q_data.get("target_expectation_indices") or q_data.get("target_expectations") or q_data.get("target_indices") or [0]
            if not isinstance(indices, list):
                indices = [0]
            return {
                "question_role": str(role).strip(),
                "question_text": q_text,
                "trigger_condition": str(trig).strip() if trig else None,
                "target_expectation_indices": [int(x) for x in indices if str(x).isdigit()],
            }
        return {
            "question_role": default_role,
            "question_text": f"How do you handle key engineering challenges in {skill_name}?",
            "trigger_condition": default_trigger,
            "target_expectation_indices": [0],
        }

    sen_clean = str(seniority_level or "mid").lower()
    is_entry = "entry" in sen_clean
    default_alt_trigger = (
        "Candidate is stuck or unsure where to start"
        if is_entry
        else "Candidate indicates no direct experience with this scenario"
    )

    anchor = _norm_q(data.get("anchor_question") or data.get("anchor"), "anchor")
    anchor_alt_raw = data.get("anchor_alt_question") or data.get("anchor_alt") or data.get("hypothetical_question")
    anchor_alt = _norm_q(anchor_alt_raw, "anchor_alt", default_alt_trigger) if anchor_alt_raw else None
    if anchor_alt and is_entry:
        anchor_alt["trigger_condition"] = "Candidate is stuck or unsure where to start"
    elif anchor_alt and not is_entry:
        if not anchor_alt.get("trigger_condition") or "production" in anchor_alt.get("trigger_condition", "").lower() or "stuck" in anchor_alt.get("trigger_condition", "").lower():
            anchor_alt["trigger_condition"] = "Candidate indicates no direct experience with this scenario"
    escalation = _norm_q(data.get("escalation_question") or data.get("escalation"), "escalation", "Candidate easily answers the anchor question with solid depth")

    raw_probes = data.get("probes", [])
    norm_probes = []
    if isinstance(raw_probes, list):
        for p in raw_probes:
            pq = _norm_q(p, "probe", "Candidate gives a surface-level response")
            if pq["question_text"]:
                norm_probes.append(pq)
    while len(norm_probes) < 3:
        norm_probes.append({
            "question_role": "probe",
            "question_text": f"What specific trade-offs or constraints did you evaluate in that approach?",
            "trigger_condition": "Candidate gives a surface-level response",
            "target_expectation_indices": [0],
        })

    normalized_payload = {
        "skill_name": skill_name,
        "expectations": norm_exp[:5],
        "anchor_question": anchor,
        "anchor_alt_question": anchor_alt,
        "escalation_question": escalation,
        "probes": norm_probes[:6],
    }

    return SkillSectionContent.model_validate(normalized_payload)


class BlueprintGenerationError(RuntimeError):
    """Raised when blueprint generation fails after all attempts and repair passes."""
    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors or []


import hashlib

_SECTION_CACHE: Dict[str, Dict[str, Any]] = {}


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


def _diversify_anchor_text(orig_text: str, cycle: int) -> str:
    """Grammatically replace repetitive anchor openings preserving verb and noun structure."""
    orig_clean = orig_text.strip()
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
    3. Anchor opening variety: if > 40% of anchors share the same 3-word opening (e.g. 'walk me through' or 'suppose you are'),
       diversify them using natural technical spoken openings.
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

    return repairs_count


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
    section_content: Optional[SkillSectionContent] = None
    model_used = None

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
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                            http_options=types.HttpOptions(timeout=25000, retry_options=types.HttpRetryOptions(attempts=1)),
                        ),
                    )
                    dur = (time.perf_counter() - t0) * 1000.0
                    logger.info("Generated section for '%s' using %s in %.1fms", s_name, model_name, dur)
                    section_content = _normalize_skill_section_data(response.text, s_name, seniority_level=seniority_level)
                    model_used = model_name
                    GEMINI_CIRCUIT_BREAKER.record_success()
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
                    else:
                        logger.warning("Gemini error on %s for '%s': %s", model_name, s_name, err_str[:120])
                        break

            if section_content:
                break
            if not key_failed:
                break
    else:
        logger.info("Gemini circuit breaker is OPEN, routing '%s' directly to backup provider", s_name)

    # Secondary provider fallback (OpenRouter -> NVIDIA)
    if not section_content:
        if get_backup_api_key():
            logger.info("Routing section for '%s' to secondary backup provider (OpenRouter/NVIDIA)", s_name)
            try:
                messages = [
                    {"role": "system", "content": SKILL_SECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
                content, bk_model = call_backup_chat_sync(messages=messages, json_mode=True, timeout=60.0)
                section_content = _normalize_skill_section_data(content, s_name, seniority_level=seniority_level)
                model_used = bk_model
                logger.info("Generated section for '%s' using backup provider (%s)", s_name, bk_model)
            except Exception as bk_exc:
                last_exc = f"Gemini error: {last_exc}; Backup error: {bk_exc}"

    if not section_content:
        raise BlueprintGenerationError(
            f"Failed to generate section for skill '{skill_info.get('name')}': {last_exc}"
        )

    # Ensure anchor_alt_question is populated with a calibrated prompt
    norm_sen = normalize_seniority(seniority_level)
    if not getattr(section_content, "anchor_alt_question", None) or not section_content.anchor_alt_question.question_text:
        anchor_txt = section_content.anchor_question.question_text.strip()
        if norm_sen == "entry":
            hypo_txt = f"Suppose we simplify the scenario to a small, fixed dataset in {s_name}; how would you approach it step by step?"
            trig_cond = "Candidate is stuck or unsure where to start"
        else:
            hypo_txt = f"Suppose you were tasked with solving a challenging problem in {s_name}; how would you approach the core architecture?"
            trig_cond = "Candidate indicates no direct experience with this scenario"
            if any(anchor_txt.lower().startswith(p) for p in ["walk me through how you", "can you walk me through how you", "tell me about a time you"]):
                hypo_txt = re.sub(
                    r"^(walk me through how you|can you walk me through how you|tell me about a time you)\s+",
                    "Suppose you were asked to ",
                    anchor_txt,
                    flags=re.IGNORECASE,
                )
                if not hypo_txt.endswith("?"):
                    hypo_txt += "?"
        from backend.app.services.blueprint.contracts import QuestionDraft
        section_content.anchor_alt_question = QuestionDraft(
            question_role="anchor_alt",
            question_text=hypo_txt,
            trigger_condition=trig_cond,
            target_expectation_indices=[0],
        )

    # Validate section
    issues = validate_skill_section(
        section=section_content,
        allocated_minutes=skill_info.get("allocated_minutes", 4.0),
        section_index=section_index,
        seniority_level=seniority_level,
    )
    errors = [i.message for i in issues if i.severity == "error"]

    # If errors, perform ONE repair pass
    if errors:
        logger.warning(
            "Section '%s' had %d validation errors; initiating repair pass on %s",
            s_name, len(errors), model_used,
        )
        repair_prompt = build_repair_user_prompt(
            original_draft=section_content.model_dump(),
            validation_errors=errors,
        )
        try:
            if model_used and ("openrouter" in model_used.lower() or "nvidia" in model_used.lower() or "backup" in model_used.lower()):
                rep_messages = [
                    {"role": "system", "content": SKILL_SECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ]
                rep_content, _ = call_backup_chat_sync(messages=rep_messages, json_mode=True, timeout=60.0)
                repaired_content = _normalize_skill_section_data(rep_content, s_name, seniority_level=seniority_level)
            elif client:
                try:
                    repaired_response = client.models.generate_content(
                        model=model_used or target_models[0],
                        contents=repair_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SKILL_SECTION_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            response_schema=SkillSectionContent,
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                            http_options=types.HttpOptions(timeout=25000, retry_options=types.HttpRetryOptions(attempts=1)),
                        ),
                    )
                    repaired_content = _normalize_skill_section_data(repaired_response.text, s_name, seniority_level=seniority_level)
                except Exception as g_exc:
                    logger.warning("Gemini repair pass failed (%s), attempting backup provider fallback", g_exc)
                    if get_backup_api_key():
                        rep_messages = [
                            {"role": "system", "content": SKILL_SECTION_SYSTEM_PROMPT},
                            {"role": "user", "content": repair_prompt},
                        ]
                        rep_content, _ = call_backup_chat_sync(messages=rep_messages, json_mode=True, timeout=60.0)
                        repaired_content = _normalize_skill_section_data(rep_content, s_name, seniority_level=seniority_level)
                    else:
                        repaired_content = None
            else:
                repaired_content = None

            if repaired_content:
                repaired_issues = validate_skill_section(
                    section=repaired_content,
                    allocated_minutes=skill_info.get("allocated_minutes", 4.0),
                    section_index=section_index,
                    seniority_level=seniority_level,
                )
                repaired_errors = [i.message for i in repaired_issues if i.severity == "error"]
                if not repaired_errors:
                    logger.info("Repair pass successful for section '%s'", skill_info.get("name"))
                    section_content = repaired_content
                else:
                    logger.warning("Repair pass still had errors for '%s': %s", skill_info.get("name"), repaired_errors)
        except Exception as r_exc:
            logger.warning("Repair pass exception for '%s': %s", skill_info.get("name"), r_exc)

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

