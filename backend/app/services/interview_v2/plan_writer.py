"""Pre-interview Plan Script Writer and Persistence for Candidly.

Transforms a deterministic PlanSkeleton into a personalized interview script
using prompt templates and bounded LLM wording generation, with strict
one-to-one slot validation, repair loop, and deterministic skeleton fallback.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models import (
    InterviewGenerationRun,
    InterviewQuestion,
    InterviewSession,
    JobApplication,
    JobPosting,
    SessionExpectationCoverage,
)
from backend.app.prompts.loader import (
    render_prompt,
    PROMPT_VERSION_PLAN,
)
from backend.app.services.interview_v2.context_hydrator import (
    HydratedInterviewContext,
    hydrate_interview_context,
)
from backend.app.services.interview_v2.plan_schema import (
    PlanSlot,
    ScriptPlan,
    build_plan_skeleton,
    validate_script_plan,
)
from backend.app.services.interview_v2 import director
from backend.app.services.llm_router import clean_json_markdown

logger = logging.getLogger(__name__)


async def write_interview_script_plan(
    skeleton: ScriptPlan,
    context: HydratedInterviewContext,
    llm_fn: Optional[Callable[..., Any]] = None,
) -> Tuple[ScriptPlan, Dict[str, Any]]:
    """Generate wording for the skeleton slots via LLM, validating exact 1:1 ID alignment."""
    metrics: Dict[str, Any] = {
        "model_name": os.getenv("INTERVIEW_PLAN_MODEL", "apac.amazon.nova-pro-v1:0"),
        "provider": "bedrock",
        "repair_attempted": False,
        "fallback_used": False,
        "validation_passed": True,
    }

    # 1. Render system and user prompts
    prompt_vars = context.to_generation_prompt_vars()
    prompt_vars["skeleton_json"] = skeleton.model_dump_json(indent=2)

    system_prompt = render_prompt("interview/plan_generation_system")
    user_prompt = render_prompt("interview/plan_generation_user", **prompt_vars)

    raw_output: Optional[Dict[str, Any]] = None

    # 2. Invoke LLM or mock
    if llm_fn:
        try:
            res = llm_fn(system_prompt=system_prompt, user_prompt=user_prompt)
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, (dict, list)):
                raw_output = res if isinstance(res, dict) else {"slots": res}
            elif isinstance(res, str):
                raw_output = json.loads(clean_json_markdown(res))
        except Exception as mock_err:
            logger.warning("Mock LLM script generation failed: %s", mock_err)
    else:
        try:
            parsed_json, call_metrics = await director.stream_decision_with_ack_first(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=1500,
                temperature=0.3,
                model_id=metrics["model_name"],
            )
            raw_output = parsed_json
            metrics.update({
                "model_name": call_metrics.get("model_name", metrics["model_name"]),
                "provider": call_metrics.get("provider", "bedrock"),
            })
        except Exception as llm_err:
            logger.error("LLM plan generation failed: %s. Falling back to skeleton.", llm_err)
            metrics["fallback_used"] = True
            metrics["fallback_reason"] = f"llm_error: {str(llm_err)[:60]}"
            return skeleton, metrics

    # 3. Apply and Validate Slots
    plan_to_validate, val_errors = _build_candidate_plan_from_raw(skeleton, raw_output)

    # 4. Repair if validation failed
    if val_errors and raw_output:
        logger.warning("Plan script validation failed: %s. Attempting repair.", val_errors)
        metrics["repair_attempted"] = True
        repair_user = render_prompt(
            "interview/plan_repair",
            skeleton_json=skeleton.model_dump_json(indent=2),
            malformed_output=json.dumps(raw_output, indent=2),
            validation_errors="\n".join(f"- {e}" for e in val_errors),
        )

        repaired_output: Optional[Dict[str, Any]] = None
        if llm_fn:
            try:
                res = llm_fn(system_prompt=system_prompt, user_prompt=repair_user)
                if hasattr(res, "__await__"):
                    res = await res
                if isinstance(res, (dict, list)):
                    repaired_output = res if isinstance(res, dict) else {"slots": res}
                elif isinstance(res, str):
                    repaired_output = json.loads(clean_json_markdown(res))
            except Exception as r_err:
                logger.warning("Mock repair failed: %s", r_err)
        else:
            try:
                repaired_json, _ = await director.stream_decision_with_ack_first(
                    system_prompt=system_prompt,
                    user_prompt=repair_user,
                    max_output_tokens=1500,
                    temperature=0.2,
                    model_id=metrics["model_name"],
                )
                repaired_output = repaired_json
            except Exception as r_err:
                logger.warning("LLM repair failed: %s", r_err)

        if repaired_output:
            plan_to_validate, val_errors = _build_candidate_plan_from_raw(skeleton, repaired_output)

    # 5. Check if candidate plan passed
    if val_errors:
        logger.warning("Plan repair failed validation (%s). Using deterministic skeleton fallback.", val_errors)
        metrics["fallback_used"] = True
        metrics["validation_passed"] = False
        metrics["fallback_reason"] = "validation_failure_post_repair"
        return skeleton, metrics

    metrics["validation_passed"] = True
    plan_to_validate.model = metrics["model_name"]
    return plan_to_validate, metrics


def _build_candidate_plan_from_raw(
    skeleton: ScriptPlan,
    raw_output: Optional[Dict[str, Any]],
) -> Tuple[ScriptPlan, List[str]]:
    """Merge LLM slot wording onto the skeleton structure with strict validation."""
    if not raw_output or not isinstance(raw_output, dict):
        return skeleton, ["Raw output was empty or not a JSON object"]

    raw_slots = raw_output.get("slots")
    if not isinstance(raw_slots, list):
        return skeleton, ["'slots' field is missing or not a list"]

    skel_map = {s.id: s for s in skeleton.slots}
    updated_slots: List[PlanSlot] = []
    errors: List[str] = []

    seen_ids = set()
    for item in raw_slots:
        if not isinstance(item, dict):
            continue
        s_id = item.get("id")
        if not s_id or s_id not in skel_map:
            errors.append(f"Unknown or missing slot id: '{s_id}'")
            continue

        seen_ids.add(s_id)
        skel_slot = skel_map[s_id]
        new_text = (item.get("text") or item.get("question_text") or "").strip()

        # If LLM returned empty or too short text, use skeleton seed
        if not new_text or len(new_text.split()) < 3:
            new_text = skel_slot.question_text

        # Validate no rubric leakage in question text
        lower_text = new_text.lower()
        if "rubric" in lower_text or "scoring level" in lower_text:
            errors.append(f"Slot {s_id} leaked rubric text: '{new_text}'")

        # Create updated slot preserving all skeleton metadata
        updated_slot = skel_slot.model_copy(update={
            "question_text": new_text,
            "source": "llm",
            "source_refs": list(item.get("source_refs") or skel_slot.source_refs),
        })
        updated_slots.append(updated_slot)

    # Check for missing slots
    for skel_id, skel_slot in skel_map.items():
        if skel_id not in seen_ids:
            # Seed missing slots from skeleton
            updated_slots.append(skel_slot)

    # Sort slots according to original skeleton order
    skel_order = [s.id for s in skeleton.slots]
    slot_lookup = {s.id: s for s in updated_slots}
    final_slots = [slot_lookup[sid] for sid in skel_order if sid in slot_lookup]

    candidate_plan = skeleton.model_copy(update={
        "slots": final_slots,
        "question_order": [s.id for s in final_slots if s.kind != "anchor_alt"],
    })

    plan_errors = validate_script_plan(candidate_plan, skeleton)
    errors.extend(plan_errors)

    return candidate_plan, errors


async def generate_or_load_script_plan(
    db: AsyncSession,
    application_id: str,
    force_regenerate: bool = False,
    session_id: Optional[str] = None,
    llm_fn: Optional[Callable[..., Any]] = None,
) -> ScriptPlan:
    """Idempotently generate or load the script plan for an application and pin to session."""
    # 1. Lookup application to get job_id
    app_stmt = select(JobApplication).where(JobApplication.id == application_id)
    app_res = await db.execute(app_stmt)
    application = app_res.scalar_one_or_none()
    if not application:
        raise ValueError(f"JobApplication not found: {application_id}")

    # 2. Check if session already has a pinned plan
    session: Optional[InterviewSession] = None
    if session_id:
        sess_stmt = (
            select(InterviewSession)
            .where(InterviewSession.id == session_id)
            .options(
                selectinload(InterviewSession.questions),
                selectinload(InterviewSession.blueprint),
            )
        )
        sess_res = await db.execute(sess_stmt)
        session = sess_res.scalar_one_or_none()
        if session and session.runtime_state and isinstance(session.runtime_state, dict):
            pinned = session.runtime_state.get("script_plan")
            if pinned and not force_regenerate:
                try:
                    return ScriptPlan.model_validate(pinned)
                except Exception as e:
                    logger.warning("Failed to validate pinned script plan for session %s: %s", session_id, e)

    # 3. Hydrate context from real database models
    context = await hydrate_interview_context(db, application.job_id, application_id)

    # 4. Deterministic skeleton
    skeleton = build_plan_skeleton(context)

    # 5. Check idempotency via InterviewGenerationRun if not forcing regeneration
    if not force_regenerate:
        run_stmt = (
            select(InterviewGenerationRun)
            .where(
                InterviewGenerationRun.application_id == application_id,
                InterviewGenerationRun.input_snapshot_hash == skeleton.input_hash,
                InterviewGenerationRun.status == "succeeded",
            )
            .order_by(InterviewGenerationRun.created_at.desc())
        )
        existing_run = (await db.execute(run_stmt)).scalars().first()
        if existing_run and existing_run.token_usage_json and isinstance(existing_run.token_usage_json, dict):
            saved_plan = existing_run.token_usage_json.get("script_plan")
            if saved_plan:
                try:
                    cached_plan = ScriptPlan.model_validate(saved_plan)
                    if session:
                        await _sync_plan_to_session(db, session, cached_plan, generation_run_id=existing_run.id)
                        await db.commit()
                    return cached_plan
                except Exception as e:
                    logger.warning("Failed to load cached plan from generation run: %s", e)

    # 6. Generate wording via LLM writer
    final_plan, metrics = await write_interview_script_plan(skeleton, context, llm_fn=llm_fn)

    # 7. Persist InterviewGenerationRun
    gen_run = InterviewGenerationRun(
        id=str(uuid.uuid4()),
        application_id=application_id,
        job_id=application.job_id,
        status="succeeded",
        model_name=metrics.get("model_name", "deterministic_skeleton"),
        prompt_template_version=PROMPT_VERSION_PLAN,
        input_snapshot_hash=skeleton.input_hash,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        token_usage_json={
            "metrics": metrics,
            "script_plan": final_plan.model_dump(),
        },
    )
    db.add(gen_run)

    # 8. Pin plan to session and sync InterviewQuestion rows
    if session:
        await _sync_plan_to_session(db, session, final_plan, generation_run_id=gen_run.id)

    await db.commit()
    return final_plan


async def _sync_plan_to_session(
    db: AsyncSession,
    session: InterviewSession,
    plan: ScriptPlan,
    generation_run_id: Optional[str] = None,
) -> None:
    """Store the plan in session.runtime_state and synchronize InterviewQuestion records."""
    # If session already in progress or completed, preserve existing runtime_state and question rows
    if session.status in ("in_progress", "completed", "cancelled"):
        logger.info("Session %s is %s; preserving existing plan and question rows", session.id, session.status)
        return

    # If questions already exist for this session, check if any have progressed past queued/pending
    existing_qs_stmt = select(InterviewQuestion).where(InterviewQuestion.session_id == session.id)
    existing_qs = (await db.execute(existing_qs_stmt)).scalars().all()
    has_in_progress = any(q.question_state not in ("queued", "pending") for q in existing_qs)
    if has_in_progress:
        logger.info("Session %s has active or completed questions; preserving existing plan and question rows", session.id)
        return

    if not session.runtime_state or not isinstance(session.runtime_state, dict):
        session.runtime_state = {}

    session.runtime_state["script_plan"] = plan.model_dump()
    session.total_questions_planned = len(plan.slots)
    session.duration_planned_mins = plan.duration_minutes
    if not has_in_progress:
        # Clear out queued questions and replace with synchronized plan slots
        await db.execute(delete(InterviewQuestion).where(InterviewQuestion.session_id == session.id))
        await db.flush()

        ordered_slots = plan.get_ordered_slots()
        for slot in ordered_slots:
            db_q = InterviewQuestion(
                id=slot.id,
                session_id=session.id,
                generation_run_id=generation_run_id,
                skill_id=slot.skill_id,
                question_index=slot.index,
                skill_name=slot.skill_name or (slot.stage.title() if slot.stage else "General"),
                skill_category="Technical" if slot.stage == "technical" else "Administrative",
                priority_tier="P0" if slot.is_required else "P1",
                question_text=slot.question_text,
                expected_key_points=slot.expected_key_points,
                follow_up_depth_allowed=slot.follow_up_depth_allowed,
                follow_up_count=0,
                question_state="queued",
                kind=slot.kind,
                personalization_context={
                    "source": slot.source,
                    "source_refs": slot.source_refs,
                    "followup_probes": slot.followup_probes,
                    "variant_group": slot.variant_group,
                },
            )
            db.add(db_q)


async def ensure_session_script_plan(
    db: AsyncSession,
    session: InterviewSession,
    force_regenerate: bool = False,
    llm_fn: Optional[Callable[..., Any]] = None,
) -> Optional[ScriptPlan]:
    """Ensure an InterviewSession has an authoritative pinned ScriptPlan and synchronized InterviewQuestion rows.

    If session.runtime_state already has a valid ScriptPlan and question rows exist (unless force_regenerate),
    returns it. Otherwise, generates or loads the ScriptPlan via generate_or_load_script_plan, pins it to session,
    synchronizes question rows, and commits to the database.
    """
    if getattr(session, "is_practice", False):
        return None
    if not force_regenerate and session.runtime_state and isinstance(session.runtime_state, dict):
        pinned = session.runtime_state.get("script_plan")
        if pinned:
            try:
                plan = ScriptPlan.model_validate(pinned)
                q_stmt = select(InterviewQuestion).where(InterviewQuestion.session_id == session.id)
                qs = (await db.execute(q_stmt)).scalars().all()
                if qs:
                    return plan
                else:
                    await _sync_plan_to_session(db, session, plan)
                    await db.commit()
                    return plan
            except Exception as e:
                logger.warning("Session %s has invalid pinned script plan: %s", session.id, e)

    plan = await generate_or_load_script_plan(
        db=db,
        application_id=session.application_id,
        force_regenerate=force_regenerate,
        session_id=session.id,
        llm_fn=llm_fn,
    )
    return plan
