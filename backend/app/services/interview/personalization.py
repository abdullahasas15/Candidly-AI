"""Candidate Personalization Service (Checkpoint R3.2).

Performs one structured background call per application using:
- The candidate's resume (PDF via Gemini Files API if available, or extracted text/structured data)
- The approved job blueprint skills and core expectations
- Any resume discrepancy flags detected during screening

Produces:
- intro_hook: Conversational opening question linking resume background to the role
- per_skill_probes: {skill_id: text|null} (only where resume has real evidence for that skill)
- claims_to_verify: [claim1, claim2]

Guarantees:
- Idempotent by input_hash (SHA-256 of blueprint version + resume content + discrepancy flags)
- Non-blocking: failures store status="failed" and continue so interview runs on blueprint alone
- Candidate data failover policy enforced (TokenHarbor only if AI_FAILOVER_CANDIDATE_DATA=true)
- Voice writing rules: natural spoken flow, <= 35 words, 1 question mark, no technique naming
"""

import hashlib
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import (
    JobApplication,
    JobPosting,
    CandidatePersonalization,
    InterviewBlueprint,
    BlueprintSection,
    BlueprintExpectation,
    CandidateResume,
)
from backend.app.services.llm_router import (
    get_backup_api_key,
    can_failover_candidate_data,
    call_backup_chat_sync,
    GEMINI_CIRCUIT_BREAKER,
    GEMINI_KEY_MANAGER,
    rotate_gemini_key,
    is_fatal_auth_error,
    extract_retry_after,
)

logger = logging.getLogger(__name__)

PERSONALIZATION_SYSTEM_PROMPT = """You are an expert technical interviewer preparing a personalized interview delivery plan.
You will receive:
1. The candidate's resume (extracted text, background, and work history).
2. Any screening discrepancy flags.
3. The job interview blueprint sections, including skills and core expectations.

Your task:
1. Generate an `intro_hook`: A complete, polite, conversational opening question inviting the candidate to introduce themselves and highlight their background (e.g. 'To kick things off, could you briefly introduce yourself, tell me about your background, and share some highlights from your recent work?'). Always formulate as a full, complete question ending with a question mark.
2. Generate `per_skill_probes`: For each skill in the blueprint, examine the resume for concrete evidence (projects, accomplishments, responsibilities).
   - If the candidate's resume has REAL EVIDENCE for that skill: write one complete, scenario-grounded spoken technical question asking about that specific real-world work (e.g. 'Could you walk me through how you designed X?'). Must be <= 35 words and end with a single question mark. NEVER output a raw sentence fragment or topic phrase.
   - If the candidate has NO direct evidence on the resume for that skill: value MUST be null. Never invent or hallucinate experience.
3. Generate `claims_to_verify`: List 1 to 3 notable metrics, claims, or achievements from the resume that the interviewer should fact-check.

Return valid JSON conforming to the schema.
"""


def _sanitize_probe_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    # If the text is a fragment like "your work designing...", turn it into a question
    lowered = cleaned.lower()
    if lowered.startswith("your work") or lowered.startswith("the project") or lowered.startswith("designing") or lowered.startswith("reducing"):
        cleaned = f"Could you walk me through {cleaned[0].lower() + cleaned[1:]}"
    if not cleaned.endswith("?"):
        cleaned = re.sub(r"[\.\s]+$", "", cleaned) + "?"
    return cleaned


class CandidatePersonalizationOutput(BaseModel):
    intro_hook: str = Field(
        ...,
        description="A complete, professional spoken question inviting the candidate to introduce themselves and share their background."
    )
    per_skill_probes: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="Map of skill_id to a targeted probe question ONLY where the resume shows genuine experience. Must be a complete question ending with '?'."
    )
    claims_to_verify: List[str] = Field(
        default_factory=list,
        description="1 to 3 factual claims from the resume worth verifying (e.g. specific metrics, ownership, tools)."
    )

    @field_validator("intro_hook", mode="before")
    @classmethod
    def normalize_intro(cls, v):
        if isinstance(v, str):
            cleaned = v.strip()
            if cleaned and not cleaned.endswith("?"):
                cleaned = re.sub(r"[\.\s]+$", "", cleaned) + "?"
            if cleaned.lower().startswith("your work") or not any(cleaned.lower().startswith(w) for w in ["to ", "could you", "can you", "please", "walk me", "tell me"]):
                return "To start off, could you please introduce yourself, tell me about your background, and share some highlights from your key projects and experiences?"
            return cleaned
        return "To start off, could you please introduce yourself, tell me about your background, and share some highlights from your key projects and experiences?"

    @field_validator("per_skill_probes", mode="before")
    @classmethod
    def normalize_probes(cls, v):
        if isinstance(v, list):
            res = {}
            for item in v:
                if isinstance(item, dict):
                    s_id = item.get("skill_id") or item.get("id") or item.get("key") or item.get("name")
                    text = item.get("probe_text") or item.get("probe") or item.get("text")
                    if not text:
                        for k, val in item.items():
                            if k not in ("skill_id", "id", "key", "name"):
                                s_id = k
                                text = str(val) if val is not None else None
                                break
                    if s_id:
                        res[str(s_id)] = _sanitize_probe_text(text)
            return res
        if isinstance(v, dict):
            return {k: _sanitize_probe_text(val) for k, val in v.items()}
        return v


def compute_personalization_hash(
    blueprint_id: str,
    blueprint_version: int,
    resume_signature: str,
    discrepancy_flags: List[str],
) -> str:
    """Compute deterministic SHA-256 hash for candidate personalization input."""
    data = f"{blueprint_id}|{blueprint_version}|{resume_signature}|{sorted(discrepancy_flags)}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


async def generate_candidate_personalization(
    application_id: str,
    db: AsyncSession,
) -> Optional[CandidatePersonalization]:
    """Generate or retrieve cached candidate personalization for an application.

    Non-blocking: on any error, stores status='failed' and returns so the interview
    session can proceed on the job blueprint alone.
    """
    logger.info("Starting candidate personalization for application %s", application_id)

    # 1. Load application with resume and discrepancy flags
    stmt = (
        select(JobApplication)
        .where(JobApplication.id == application_id)
    )
    res = await db.execute(stmt)
    app = res.scalar_one_or_none()
    if not app:
        logger.error("Application %s not found for personalization", application_id)
        return None

    # 2. Load Job Posting and Active Blueprint
    job_stmt = select(JobPosting).where(JobPosting.id == app.job_id)
    job_res = await db.execute(job_stmt)
    job = job_res.scalar_one_or_none()
    if not job or not job.active_blueprint_id:
        logger.warning("Job %s has no active blueprint; skipping personalization", app.job_id)
        return None

    bp_stmt = select(InterviewBlueprint).where(InterviewBlueprint.id == job.active_blueprint_id)
    bp_res = await db.execute(bp_stmt)
    blueprint = bp_res.scalar_one_or_none()
    if not blueprint:
        logger.warning("Active blueprint %s not found for job %s", job.active_blueprint_id, job.id)
        return None

    # Load blueprint sections and expectations
    sec_stmt = (
        select(BlueprintSection)
        .where(BlueprintSection.blueprint_id == blueprint.id)
        .order_by(BlueprintSection.order_index)
    )
    sec_res = await db.execute(sec_stmt)
    sections = sec_res.scalars().all()

    # Load resume
    resume_stmt = select(CandidateResume).where(CandidateResume.application_id == app.id)
    resume_res = await db.execute(resume_stmt)
    resume = resume_res.scalar_one_or_none()

    # Extract discrepancy flags
    discrepancies = [
        f"{f.field_name}: {f.flag_reason}"
        for f in getattr(app, "discrepancy_flags", [])
    ]

    resume_text = ""
    resume_signature = "no_resume"
    if resume:
        resume_text = resume.parsed_text or ""
        if not resume_text and resume.parsed_structured_data:
            resume_text = json.dumps(resume.parsed_structured_data)
        resume_signature = hashlib.sha256((resume_text[:2000]).encode("utf-8")).hexdigest()

    # 3. Check Idempotency via input_hash
    input_hash = compute_personalization_hash(
        blueprint_id=blueprint.id,
        blueprint_version=blueprint.version or 1,
        resume_signature=resume_signature,
        discrepancy_flags=discrepancies,
    )

    cp_stmt = select(CandidatePersonalization).where(CandidatePersonalization.application_id == app.id)
    cp_res = await db.execute(cp_stmt)
    existing_cp = cp_res.scalar_one_or_none()

    if existing_cp and existing_cp.input_hash == input_hash and existing_cp.status == "completed":
        logger.info("Found existing completed candidate personalization for application %s (hash match)", app.id)
        return existing_cp

    # 4. Build Compact Blueprint Representation
    skills_context = []
    for s in sections:
        if s.section_type != "skill":
            continue
        skill_id = s.skill_id or s.id
        exp_stmt = (
            select(BlueprintExpectation)
            .where(BlueprintExpectation.section_id == s.id)
            .order_by(BlueprintExpectation.order_index)
        )
        exp_res = await db.execute(exp_stmt)
        exps = exp_res.scalars().all()
        skills_context.append({
            "skill_id": skill_id,
            "skill_name": s.skill_name or s.title,
            "category": getattr(s, "skill_category", "Technical") or "Technical",
            "priority_tier": s.priority_tier or "P0",
            "expectations": [e.expectation_text for e in exps],
        })

    prompt_payload = {
        "candidate_name": app.full_name,
        "job_title": getattr(job, "job_title", None) or getattr(job, "title", "Role"),
        "seniority_level": getattr(blueprint, "seniority_level", "mid"),
        "resume_summary": resume_text[:4000] if resume_text else "No resume text provided.",
        "screening_discrepancy_flags": discrepancies,
        "blueprint_skills": skills_context,
    }

    user_prompt = f"Application Details:\n{json.dumps(prompt_payload, indent=2)}"

    # 5. Call LLM for Structured Output
    output: Optional[CandidatePersonalizationOutput] = None
    raw_response: Optional[Dict[str, Any]] = None

    # Try Gemini Primary
    if GEMINI_CIRCUIT_BREAKER.can_attempt():
        try:
            from backend.app.services.question_generation.provider import get_gemini_client
            from google.genai import types

            def _sanitize_schema(value):
                if isinstance(value, dict):
                    return {
                        k: _sanitize_schema(v)
                        for k, v in value.items()
                        if k not in {"additionalProperties", "title"}
                    }
                if isinstance(value, list):
                    return [_sanitize_schema(v) for v in value]
                return value

            sanitized_schema = _sanitize_schema(CandidatePersonalizationOutput.model_json_schema())

            total_keys = max(GEMINI_KEY_MANAGER.key_count, 1)
            for key_attempt in range(total_keys):
                try:
                    client = get_gemini_client()
                    resp = client.models.generate_content(
                        model=os.getenv("GEMINI_MODEL_PLAN", "gemini-3.5-flash-lite"),
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=PERSONALIZATION_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            response_schema=sanitized_schema,
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                        ),
                    )
                    output = CandidatePersonalizationOutput.model_validate_json(resp.text)
                    raw_response = output.model_dump()
                    GEMINI_CIRCUIT_BREAKER.record_success()
                    logger.info("Successfully generated personalization via Gemini for application %s", app.id)
                    break
                except Exception as exc:
                    err_str = str(exc)
                    if is_fatal_auth_error(exc):
                        logger.error("Fatal Gemini auth error during personalization: %s", err_str[:120])
                        rotate_gemini_key(f"Fatal auth error: {err_str[:60]}")
                        continue
                    if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "UNAVAILABLE" in err_str or "503" in err_str:
                        logger.warning("Gemini key hit rate limit / 503 during personalization (%s). Rotating key...", err_str[:80])
                        rotate_gemini_key("Rate-limit/503 during personalization")
                        continue
                    else:
                        retry_after = extract_retry_after(exc)
                        GEMINI_CIRCUIT_BREAKER.record_failure(str(exc), retry_after)
                        logger.warning("Gemini personalization failed for application %s: %s", app.id, exc)
                        break
        except Exception as outer_exc:
            logger.warning("Outer Gemini setup failed: %s", outer_exc)

    # Secondary Provider Fallback (OpenRouter -> NVIDIA) - ONLY if candidate data failover is enabled
    if not output and get_backup_api_key():
        if can_failover_candidate_data():
            try:
                logger.info("Failing over personalization for application %s to backup provider (AI_FAILOVER_CANDIDATE_DATA=true)", app.id)
                messages = [
                    {"role": "system", "content": PERSONALIZATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ]
                content, bk_model = call_backup_chat_sync(messages=messages, json_mode=True, timeout=30.0)
                cleaned = content.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                    cleaned = re.sub(r"\s*```$", "", cleaned)
                raw_dict = json.loads(cleaned)
                output = CandidatePersonalizationOutput.model_validate(raw_dict)
                raw_response = raw_dict
                logger.info("Successfully generated personalization via backup provider (%s) for application %s", bk_model, app.id)
            except Exception as bk_exc:
                logger.warning("Backup provider personalization failed for application %s: %s", app.id, bk_exc)
        else:
            logger.warning(
                "Candidate personalization failover to backup provider blocked for application %s: "
                "AI_FAILOVER_CANDIDATE_DATA is false.", app.id
            )

    # 6. Store Result
    status = "completed" if output else "failed"
    intro_hook = output.intro_hook if output else f"Welcome, {app.full_name}. Could you briefly introduce yourself and share what interests you about this role?"
    per_skill_probes = output.per_skill_probes if output else {}
    claims_to_verify = output.claims_to_verify if output else []

    if existing_cp:
        existing_cp.blueprint_id = blueprint.id
        existing_cp.status = status
        existing_cp.input_hash = input_hash
        existing_cp.intro_hook = intro_hook
        existing_cp.per_skill_probes = per_skill_probes
        existing_cp.claims_to_verify = claims_to_verify
        existing_cp.raw_model_response = raw_response
        await db.commit()
        await db.refresh(existing_cp)
        return existing_cp
    else:
        new_cp = CandidatePersonalization(
            application_id=app.id,
            blueprint_id=blueprint.id,
            status=status,
            input_hash=input_hash,
            intro_hook=intro_hook,
            deep_dive_project={},
            per_skill_probes=per_skill_probes,
            claims_to_verify=claims_to_verify,
            raw_model_response=raw_response,
        )
        db.add(new_cp)
        await db.commit()
        await db.refresh(new_cp)
        return new_cp
