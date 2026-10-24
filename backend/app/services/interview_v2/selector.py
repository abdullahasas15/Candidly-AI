"""Live Bounded-Agentic Selector for Candidly Voice Interview.

Evaluates each candidate answer against the current question and plan context,
selecting one of five bounded actions:
- ADVANCE: Proceed to next stored planned question using exact stored wording
- FOLLOW_UP: Ask a concise, grounded probe on the current skill (<= 28 words)
- CLARIFY_OR_REPEAT: Ask for clarification or repeat current question
- CANDIDATE_QA: Answer candidate question using authoritative job facts
- END_INTERVIEW: Speak prepared closing and conclude
"""

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, model_validator

from backend.app.prompts.loader import (
    render_prompt,
    PROMPT_VERSION_SELECTOR,
)
from backend.app.services.interview_v2.plan_schema import PlanSlot, ScriptPlan
from backend.app.services.interview_v2 import director
from backend.app.services.llm_router import clean_json_markdown

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = [
    "ADVANCE",
    "FOLLOW_UP",
    "CLARIFY_OR_REPEAT",
    "SWAP_QUESTION",
    "CANDIDATE_QA",
    "END_INTERVIEW",
]

ALLOWED_REASON_CODES = [
    "planned_next",
    "answer_gap",
    "ambiguity",
    "transcription_issue",
    "candidate_question",
    "no_knowledge",
    "time_limit",
    "plan_complete",
    "depth_probe",
]


class SelectorInput(BaseModel):
    candidate_and_job_summary: str
    past_two_turns: List[Dict[str, str]] = Field(default_factory=list)
    current_question: Dict[str, Any]
    candidate_answer: str
    next_planned_question: Optional[Dict[str, Any]] = None
    optional_prepared_followups: List[Dict[str, Any]] = Field(default_factory=list)
    # Server-side deterministic signal: the committed answer reads as "I don't
    # know / no idea / not familiar". The LLM must answer with SWAP_QUESTION.
    no_knowledge_signal: bool = False
    # Prepared alternative question on the same skill (anchor variant) used when
    # swapping; the conductor resolves the authoritative wording from the plan.
    alternative_question: Optional[Dict[str, Any]] = None
    followups_remaining: int = 1
    remaining_time_mins: float = 10.0
    allowed_actions: List[str] = Field(default_factory=lambda: list(ALLOWED_ACTIONS))
    # Competency-driven enrichment (backward compatible defaults):
    skill_rubric: Dict[str, str] = Field(default_factory=dict, description="L1-L5 anchors for the active skill")
    escalation_question: Optional[str] = None
    candidate_hooks: List[str] = Field(default_factory=list, description="Candidate projects/claims for this skill")
    covered_expectations: List[str] = Field(default_factory=list)
    hint_or_alt_used_on_skill: bool = False
    # Structured candidate dossier (stable per session; lives in the cached
    # prompt prefix so the interviewer always knows whose work it is probing).
    candidate_dossier: Dict[str, Any] = Field(default_factory=dict)
    # Last rubric level estimated on this skill — lets the escalation ladder
    # CONTINUE across turns (L2 shown → probe toward L3/L4 next) instead of
    # re-estimating blind each turn.
    last_estimated_level: Optional[str] = None


class SelectorOutput(BaseModel):
    decision: str
    planned_question_id: Optional[str] = None
    follow_up_question: Optional[str] = None
    clarify_text: Optional[str] = None
    ack: Optional[str] = None
    bridge: Optional[str] = None
    reason_code: str = "planned_next"
    rationale: Optional[str] = None
    confidence: float = 0.9
    estimated_rubric_level: Optional[str] = None
    covered_expectations: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # Normalize decision to uppercase, mapping action/decision synonyms
        raw_dec = str(data.get("decision") or data.get("action") or "").upper().strip()
        if raw_dec in ("NEXT", "NEW_TOPIC", "ADVANCE", "TRANSITION"):
            raw_dec = "ADVANCE"
        elif raw_dec in ("PROBE", "FOLLOW_UP", "ESCALATE", "HYPOTHETICAL"):
            raw_dec = "FOLLOW_UP"
        elif raw_dec in ("CLARIFY", "CLARIFY_OR_REPEAT", "REPHRASE", "OFF_TOPIC"):
            raw_dec = "CLARIFY_OR_REPEAT"
        elif raw_dec in ("SWAP", "SWAP_QUESTION", "ALT", "ALTERNATIVE", "NO_EXPERIENCE", "NO_KNOWLEDGE"):
            raw_dec = "SWAP_QUESTION"
        elif raw_dec in ("CANDIDATE_QA", "QA_REPLY"):
            raw_dec = "CANDIDATE_QA"
        elif raw_dec in ("CLOSE", "END", "END_INTERVIEW"):
            raw_dec = "END_INTERVIEW"
        data["decision"] = raw_dec

        # Map question / followup to follow_up_question
        if not data.get("follow_up_question"):
            if data.get("question"):
                data["follow_up_question"] = data["question"]
            elif data.get("followup"):
                data["follow_up_question"] = data["followup"]

        # Map clarify_text / clarifier
        if not data.get("clarify_text") and data.get("clarifier"):
            data["clarify_text"] = data["clarifier"]

        # Normalize reason_code
        rc = str(data.get("reason_code") or "planned_next").lower().strip()
        if rc not in ALLOWED_REASON_CODES:
            rc = "planned_next"
        data["reason_code"] = rc

        # Normalize estimated rubric level (L1-L5 or UNASSESSED)
        lvl = str(data.get("estimated_rubric_level") or "").upper().strip()
        if lvl in ("L1", "L2", "L3", "L4", "L5", "UNASSESSED"):
            data["estimated_rubric_level"] = lvl
        else:
            data.pop("estimated_rubric_level", None)

        # Sanitize ack and bridge: strip question marks
        if data.get("ack"):
            data["ack"] = str(data["ack"]).replace("?", "").strip()
        if data.get("bridge"):
            data["bridge"] = str(data["bridge"]).replace("?", "").strip()

        # Sanitize follow_up_question: ensure single question mark if provided
        if data.get("follow_up_question"):
            fq = str(data["follow_up_question"]).strip()
            if not fq.endswith("?"):
                fq += "?"
            data["follow_up_question"] = fq

        return data


def validate_selector_output(output: SelectorOutput, input_data: SelectorInput) -> List[str]:
    """Validate selector output constraints according to Section 8."""
    errors: List[str] = []

    if output.decision not in input_data.allowed_actions:
        errors.append(f"Decision '{output.decision}' is not in allowed_actions {input_data.allowed_actions}")

    if output.decision == "ADVANCE":
        next_q = input_data.next_planned_question
        if next_q:
            expected_id = next_q.get("id")
            if output.planned_question_id and output.planned_question_id != expected_id:
                # Lenient coercion: override to expected_id
                output.planned_question_id = expected_id
            elif not output.planned_question_id:
                output.planned_question_id = expected_id
        else:
            errors.append("ADVANCE chosen but no next_planned_question is available")

    elif output.decision == "FOLLOW_UP":
        if input_data.followups_remaining <= 0:
            errors.append("FOLLOW_UP chosen but followups_remaining is 0")
        if not output.follow_up_question:
            errors.append("FOLLOW_UP chosen but follow_up_question is missing")
        else:
            word_count = len(output.follow_up_question.split())
            if word_count > 28:
                errors.append(f"Follow-up question exceeds 28 words ({word_count} words)")
            # Check for repetition of current question text
            cur_text = (input_data.current_question.get("text") or "").lower().strip()
            if cur_text and cur_text in output.follow_up_question.lower():
                errors.append("Follow-up question verbatim repeats current question text")

    elif output.decision == "CLARIFY_OR_REPEAT":
        if not output.clarify_text:
            cur_text = input_data.current_question.get("text") or "Could you clarify that?"
            output.clarify_text = f"Could you clarify your answer regarding that?"

    elif output.decision == "SWAP_QUESTION":
        # The conductor resolves the authoritative alternative wording from the
        # plan; surface the prepared alternative (if any) as the follow-up text.
        if input_data.alternative_question and not output.follow_up_question:
            output.follow_up_question = input_data.alternative_question.get("text") or None
        if not output.reason_code or output.reason_code == "planned_next":
            output.reason_code = "no_knowledge"

    # Check ack word count
    if output.ack and len(output.ack.split()) > 10:
        # Truncate rather than rejecting
        output.ack = " ".join(output.ack.split()[:8])

    # Check bridge word count
    if output.bridge and len(output.bridge.split()) > 14:
        output.bridge = " ".join(output.bridge.split()[:12])

    return errors


async def select_next_interview_action(
    input_data: SelectorInput,
    llm_fn: Optional[Callable[..., Any]] = None,
    on_stream_ack: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[SelectorOutput, Dict[str, Any]]:
    """Execute live bounded-agentic selection with repair loop and safe fallback."""
    metrics: Dict[str, Any] = {
        "model_name": os.getenv("INTERVIEW_DIRECTOR_MODEL", "apac.amazon.nova-pro-v1:0"),
        "provider": "bedrock",
        "repair_attempted": False,
        "fallback_used": False,
        "fallback_reason": None,
        "validation_passed": True,
    }

    # 1. Render selector prompts
    next_planned_id = input_data.next_planned_question.get("id") if input_data.next_planned_question else ""
    user_prompt = render_prompt(
        "interview/selector_user",
        candidate_and_job_summary=input_data.candidate_and_job_summary,
        past_two_turns_json=json.dumps(input_data.past_two_turns, indent=2),
        current_question_json=json.dumps(input_data.current_question, indent=2),
        candidate_answer=input_data.candidate_answer,
        next_planned_question_json=json.dumps(input_data.next_planned_question, indent=2) if input_data.next_planned_question else "null",
        optional_prepared_followups_json=json.dumps(input_data.optional_prepared_followups, indent=2),
        no_knowledge_signal="true" if input_data.no_knowledge_signal else "false",
        alternative_question_json=json.dumps(input_data.alternative_question, indent=2) if input_data.alternative_question else "null",
        followups_remaining=str(input_data.followups_remaining),
        remaining_time_mins=f"{input_data.remaining_time_mins:.1f}",
        allowed_actions_json=json.dumps(input_data.allowed_actions),
        skill_rubric_json=json.dumps(input_data.skill_rubric, indent=2) if input_data.skill_rubric else "{}",
        escalation_question=input_data.escalation_question or "(none)",
        candidate_hooks_json=json.dumps(input_data.candidate_hooks, indent=2) if input_data.candidate_hooks else "[]",
        covered_expectations_json=json.dumps(input_data.covered_expectations, indent=2) if input_data.covered_expectations else "[]",
        hint_or_alt_used_on_skill="true" if input_data.hint_or_alt_used_on_skill else "false",
        candidate_dossier_json=json.dumps(input_data.candidate_dossier, indent=2) if input_data.candidate_dossier else "{}",
        last_estimated_level=input_data.last_estimated_level or "UNASSESSED",
        followups_used_on_skill=str(int(input_data.current_question.get("followup_count", 0) or 0)),
        max_followups_on_skill=str(int(input_data.current_question.get("max_followup_depth", 2) or 2)),
    )
    system_prompt = render_prompt("interview/selector_system")

    # Stable/volatile split for provider prefix caching: everything above the
    # LIVE TURN marker is identical across consecutive turns of the same skill.
    split_marker = "=== LIVE TURN"
    stable_prefix, marker, volatile_suffix = user_prompt.partition(split_marker)
    user_stable = stable_prefix if marker else None
    user_volatile = marker + volatile_suffix if marker else None

    raw_dict: Optional[Dict[str, Any]] = None

    # 2. Call LLM or mock
    if llm_fn:
        try:
            res = llm_fn(
                question_text=input_data.current_question.get("text", ""),
                answer_text=input_data.candidate_answer,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, dict):
                raw_dict = res
            elif isinstance(res, str):
                raw_dict = json.loads(clean_json_markdown(res))
        except Exception as mock_err:
            logger.warning("Mock LLM selector call failed: %s", mock_err)
    else:
        try:
            call_kwargs: Dict[str, Any] = {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_output_tokens": 300,
                "temperature": 0.1,
                "on_ack_ready": on_stream_ack,
                "model_id": metrics["model_name"],
            }
            # Prefix-caching split: pass stable/volatile parts when available so
            # the router can attach provider cache points.
            if user_stable and user_volatile:
                call_kwargs["user_stable_prefix"] = user_stable
                call_kwargs["user_volatile_suffix"] = user_volatile
                call_kwargs.pop("user_prompt", None)
            parsed_json, call_metrics = await director.stream_decision_with_ack_first(**call_kwargs)
            raw_dict = parsed_json
            metrics.update({
                "model_name": call_metrics.get("model_name", metrics["model_name"]),
                "provider": call_metrics.get("provider", "bedrock"),
                "ttft_ms": call_metrics.get("ttft_ms"),
            })
        except Exception as llm_err:
            logger.error("Selector LLM call failed: %s", llm_err)
            metrics["fallback_reason"] = f"llm_error: {str(llm_err)[:60]}"

    # 3. Parse and Validate
    candidate_output: Optional[SelectorOutput] = None
    val_errors: List[str] = []

    if raw_dict and isinstance(raw_dict, dict):
        try:
            candidate_output = SelectorOutput.model_validate(raw_dict)
            val_errors = validate_selector_output(candidate_output, input_data)
        except Exception as parse_err:
            val_errors = [f"JSON schema validation error: {parse_err}"]

    # 4. Repair loop if validation failed
    if val_errors:
        logger.warning("Selector output validation failed (%s). Attempting repair.", val_errors)
        metrics["repair_attempted"] = True
        repair_user = render_prompt(
            "interview/selector_repair",
            validation_error="; ".join(val_errors),
            malformed_output=json.dumps(raw_dict) if raw_dict else "None",
            next_planned_id=next_planned_id,
            allowed_actions_json=json.dumps(input_data.allowed_actions),
        )

        repaired_dict: Optional[Dict[str, Any]] = None
        if llm_fn:
            try:
                res = llm_fn(system_prompt=system_prompt, user_prompt=repair_user)
                if hasattr(res, "__await__"):
                    res = await res
                if isinstance(res, dict):
                    repaired_dict = res
                elif isinstance(res, str):
                    repaired_dict = json.loads(clean_json_markdown(res))
            except Exception as r_err:
                logger.warning("Mock repair failed: %s", r_err)
        else:
            try:
                repaired_json, _ = await director.stream_decision_with_ack_first(
                    system_prompt=system_prompt,
                    user_prompt=repair_user,
                    max_output_tokens=300,
                    temperature=0.2,
                    model_id=metrics["model_name"],
                )
                repaired_dict = repaired_json
            except Exception as r_err:
                logger.warning("Selector repair call failed: %s", r_err)

        if repaired_dict and isinstance(repaired_dict, dict):
            try:
                repaired_output = SelectorOutput.model_validate(repaired_dict)
                repaired_errors = validate_selector_output(repaired_output, input_data)
                if not repaired_errors:
                    candidate_output = repaired_output
                    val_errors = []
            except Exception as r_val_err:
                logger.warning("Repaired selector output still invalid: %s", r_val_err)

    # 5. Fallback if still invalid
    if not candidate_output or val_errors:
        metrics["validation_passed"] = False
        metrics["fallback_used"] = True
        if not metrics.get("fallback_reason"):
            metrics["fallback_reason"] = "selector_validation_failure"
        fallback_decision, fb_metrics = _generate_plan_aware_fallback(input_data, metrics["fallback_reason"])
        metrics.update(fb_metrics)
        return fallback_decision, metrics

    # Hard guard: a no-knowledge admission ("I don't know") must never be probed
    # or clarified, regardless of what the model returned.
    if input_data.no_knowledge_signal and candidate_output.decision in ("FOLLOW_UP", "CLARIFY_OR_REPEAT"):
        candidate_output = SelectorOutput(
            decision="SWAP_QUESTION",
            follow_up_question=(input_data.alternative_question or {}).get("text"),
            ack=candidate_output.ack,
            bridge=candidate_output.bridge or "No problem.",
            reason_code="no_knowledge",
            rationale="Candidate indicated no knowledge; swapping question",
            confidence=0.9,
        )

    # Ladder step 1 enforcement: on the FIRST admission for a skill (no hint or
    # alternative used yet), even an ADVANCE becomes a warm swap — the candidate
    # deserves the easier angle before the topic is dropped.
    if (
        input_data.no_knowledge_signal
        and not input_data.hint_or_alt_used_on_skill
        and candidate_output.decision == "ADVANCE"
        and (input_data.alternative_question or {}).get("text")
    ):
        candidate_output = SelectorOutput(
            decision="SWAP_QUESTION",
            follow_up_question=input_data.alternative_question["text"],
            ack=candidate_output.ack,
            bridge=candidate_output.bridge or "No problem.",
            reason_code="no_knowledge",
            rationale="First no-knowledge admission; offering the simpler alternative before moving on",
            confidence=0.85,
        )

    # Conversational-depth guard: an interview must not feel like a rapid-fire
    # quiz. When the candidate just gave a substantive answer that has NOT yet
    # demonstrated L4/L5 depth, follow-up depth remains, and time allows, one
    # probing follow-up takes precedence over advancing. When the model already
    # assessed the answer at L4/L5, its ADVANCE is respected — never interrogate
    # a proven topic.
    answer_words = len((input_data.candidate_answer or "").split())
    already_proven = (candidate_output.estimated_rubric_level or "").upper() in ("L4", "L5")
    if (
        candidate_output.decision == "ADVANCE"
        and not input_data.no_knowledge_signal
        and not already_proven
        and answer_words >= 15
        and input_data.followups_remaining > 0
        and (input_data.remaining_time_mins or 0) > 2.0
        and not candidate_output.follow_up_question
    ):
        grounded = None
        if input_data.escalation_question:
            grounded = input_data.escalation_question
        for probe in input_data.optional_prepared_followups or []:
            if probe.get("text"):
                grounded = probe["text"]
                break
        if not grounded:
            grounded = "Can you take that one level deeper — the trade-offs or failure cases?"
        candidate_output = SelectorOutput(
            decision="FOLLOW_UP",
            follow_up_question=grounded,
            ack=candidate_output.ack,
            bridge=candidate_output.bridge,
            reason_code="depth_probe",
            rationale="Substantive answer below L4 depth with follow-up room; probing before advancing",
            confidence=0.7,
            estimated_rubric_level=candidate_output.estimated_rubric_level,
            covered_expectations=candidate_output.covered_expectations,
        )

    metrics["validation_passed"] = True
    metrics["fallback_used"] = False
    return candidate_output, metrics


def _generate_plan_aware_fallback(input_data: SelectorInput, reason: str = "fallback") -> Tuple[SelectorOutput, Dict[str, Any]]:
    """Deterministic, plan-aware fallback that guarantees never producing generic canned questions."""
    next_q = input_data.next_planned_question
    fallback_metrics = {
        "fallback_used": True,
        "fallback_reason": reason,
        "validation_passed": False,
    }

    # A no-knowledge admission swaps the question (or advances) — never a probe.
    if getattr(input_data, "no_knowledge_signal", False):
        return (
            SelectorOutput(
                decision="SWAP_QUESTION",
                follow_up_question=(input_data.alternative_question or {}).get("text"),
                ack="No problem.",
                bridge=None,
                reason_code="no_knowledge",
                rationale="Deterministic no-knowledge swap",
                confidence=0.5,
            ),
            fallback_metrics,
        )

    if next_q and input_data.remaining_time_mins > 1.0:
        out = SelectorOutput(
            decision="ADVANCE",
            planned_question_id=next_q.get("id"),
            ack="Understood.",
            bridge="Moving forward.",
            reason_code="planned_next",
            rationale="Deterministic fallback advance to next planned question",
            confidence=0.5,
        )
        return out, fallback_metrics

    # If time nearly exhausted or no next question, gracefully conclude
    out = SelectorOutput(
        decision="END_INTERVIEW",
        planned_question_id=None,
        ack="Thank you.",
        bridge=None,
        reason_code="plan_complete" if not next_q else "time_limit",
        rationale="Deterministic fallback conclude interview",
        confidence=0.5,
    )
    return out, fallback_metrics
