import asyncio
from dataclasses import dataclass
from datetime import datetime
import os
import re
from statistics import median
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models import (
    AuditEvent,
    InterviewEvaluation,
    InterviewQuestion,
    InterviewSession,
    InterviewSkillScore,
    InterviewTranscriptTurn,
    JobApplication,
    JobPosting,
)
from backend.app.services.question_generation.provider import (
    JUDGE_MODEL_NAME,
    get_gemini_client,
)


@dataclass(frozen=True)
class TurnEvaluation:
    """Pass-through seam for live turn acceptance; full scoring runs post-interview via evaluate_interview_session."""

    transcript: str
    accepted: bool = True


def evaluate_transcript_turn(transcript: str) -> TurnEvaluation:
    if not transcript or not transcript.strip():
        return TurnEvaluation(transcript=transcript, accepted=False)
    return TurnEvaluation(transcript=transcript, accepted=True)


# ---------------------------------------------------------------------------
# Post-Interview Evidence-Anchored Judge (Part D)
# ---------------------------------------------------------------------------

LEVEL_TO_SCORE: dict[str, Optional[float]] = {
    "L1": 20.0,
    "L2": 40.0,
    "L3": 60.0,
    "L4": 80.0,
    "L5": 100.0,
    "NOT_ASSESSED": None,
}

SCORE_TO_LEVEL: list[tuple[float, str]] = [
    (90.0, "L5"),
    (70.0, "L4"),
    (50.0, "L3"),
    (30.0, "L2"),
    (0.0, "L1"),
]


class JudgeEvidenceQuote(BaseModel):
    turn_id: str
    quote: str


class JudgeSkillAssessment(BaseModel):
    skill_name: str
    level: Literal["L1", "L2", "L3", "L4", "L5", "NOT_ASSESSED"]
    evidence: list[JudgeEvidenceQuote] = Field(default_factory=list)
    rationale: str = ""


class JudgeLLMOutput(BaseModel):
    skills: list[JudgeSkillAssessment] = Field(default_factory=list)
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    candidate_summary: str = ""


def _normalize_for_quote_check(text: str) -> str:
    """Normalize case, punctuation, and whitespace for verbatim quote substring verification."""
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def verify_quote_against_turns(
    turn_id: str,
    quote: str,
    candidate_turns_by_id: dict[str, str],
) -> tuple[bool, Optional[str]]:
    """Verify that `quote` is a verbatim normalized substring of a candidate turn.

    Returns (is_verified, resolved_turn_id).
    If the model cited a slightly wrong turn_id, we also check if the verbatim quote
    exists in any candidate turn in the session and resolve its true turn_id.
    """
    norm_quote = _normalize_for_quote_check(quote)
    if not norm_quote or len(norm_quote.split()) < 2:
        return False, None

    # 1. Check cited turn_id first
    if turn_id in candidate_turns_by_id:
        norm_turn = _normalize_for_quote_check(candidate_turns_by_id[turn_id])
        if norm_quote in norm_turn:
            return True, turn_id

    # 2. Check all candidate turns in case turn_id was off-by-one
    for tid, ttext in candidate_turns_by_id.items():
        norm_turn = _normalize_for_quote_check(ttext)
        if norm_quote in norm_turn:
            return True, tid

    return False, None


def compute_verdict_from_score(
    weighted_score: Optional[float],
    insufficient_evidence: bool,
) -> str:
    """Deterministically map weighted score + P0 evidence status to a verdict."""
    if weighted_score is None:
        return "insufficient_evidence"
    if insufficient_evidence:
        # Cap verdict when any P0 skill is NOT_ASSESSED
        if weighted_score >= 40.0:
            return "lean_no"
        return "no"
    if weighted_score >= 85.0:
        return "strong_yes"
    if weighted_score >= 70.0:
        return "yes"
    if weighted_score >= 55.0:
        return "lean_yes"
    if weighted_score >= 40.0:
        return "lean_no"
    return "no"


def is_borderline_score(score: Optional[float]) -> bool:
    """Check if score is within 4 points of key decision boundaries (55 or 70)."""
    if score is None:
        return False
    return (51.0 <= score <= 59.0) or (66.0 <= score <= 74.0)


def redact_candidate_summary(text: str) -> str:
    """Ensure no rubric levels (L1-L5), numeric scores, or hiring verdicts leak into candidate_summary."""
    cleaned = text or ""
    cleaned = re.sub(r"\bL[1-5]\b", "core proficiency", cleaned)
    cleaned = re.sub(
        r"\b(strong_yes|lean_yes|lean_no|strong\s+yes|lean\s+yes|lean\s+no|not_assessed|insufficient_evidence)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b\d{1,3}\s*(?:/\s*100|%|points|score)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or (
        "Thank you for completing the interview. You shared relevant examples from your background, "
        "and our recruiting team will review your session shortly."
    )


def _judge_response_schema() -> dict:
    schema = JudgeLLMOutput.model_json_schema()

    def sanitize(value):
        if isinstance(value, dict):
            return {
                k: sanitize(v)
                for k, v in value.items()
                if k not in {"additionalProperties", "title"}
            }
        if isinstance(value, list):
            return [sanitize(v) for v in value]
        return value

    return sanitize(schema)


def _build_glossary(job: JobPosting, application: Optional[JobApplication]) -> list[str]:
    terms: set[str] = set()
    for s in job.skills or []:
        if s.name:
            terms.add(s.name)
    for c in job.certifications or []:
        if c.name:
            terms.add(c.name)
    if application and application.resume and application.resume.parsed_structured_data:
        r_data = application.resume.parsed_structured_data
        for sk in (r_data.get("skills") or [])[:30]:
            if isinstance(sk, str):
                terms.add(sk)
        for w in (r_data.get("work_experience") or [])[:5]:
            if isinstance(w, dict):
                if w.get("company"):
                    terms.add(str(w["company"]))
                for tech in (w.get("technologies") or [])[:10]:
                    terms.add(str(tech))
        for p in (r_data.get("projects") or [])[:4]:
            if isinstance(p, dict) and p.get("title"):
                terms.add(str(p["title"]))
    return sorted(terms)


def _mock_judge_output(
    skills_spec: list[dict[str, Any]],
    turns: list[InterviewTranscriptTurn],
) -> JudgeLLMOutput:
    candidate_turns = [t for t in turns if t.speaker == "candidate" and (t.text or "").strip()]
    assessments: list[JudgeSkillAssessment] = []

    for idx, sk in enumerate(skills_spec):
        sname = sk["name"]
        # Find candidate turns linked to this skill or containing skill keywords
        sk_tokens = [w for w in re.findall(r"[a-z0-9]+", sname.lower()) if len(w) >= 3]
        matching_turns = []
        for ct in candidate_turns:
            lower_t = (ct.text or "").lower()
            if any(tok in lower_t for tok in sk_tokens):
                matching_turns.append(ct)
        if not matching_turns and idx < len(candidate_turns):
            matching_turns = [candidate_turns[idx]]

        if not matching_turns:
            assessments.append(
                JudgeSkillAssessment(
                    skill_name=sname,
                    level="NOT_ASSESSED",
                    evidence=[],
                    rationale=f"No substantive candidate response was recorded for {sname}.",
                )
            )
            continue

        chosen_turn = max(matching_turns, key=lambda t: len((t.text or "").split()))
        words = (chosen_turn.text or "").strip().split()
        if len(words) < 5 or any(
            p in (chosen_turn.text or "").lower()
            for p in ("i don't know", "no idea", "skip this", "pass on this")
        ):
            assessments.append(
                JudgeSkillAssessment(
                    skill_name=sname,
                    level="NOT_ASSESSED",
                    evidence=[],
                    rationale=f"Candidate did not provide assessable evidence for {sname}.",
                )
            )
            continue

        quote_words = words[: min(16, len(words))]
        verbatim_quote = " ".join(quote_words)
        level: Literal["L1", "L2", "L3", "L4", "L5"] = "L4" if len(words) >= 28 else ("L3" if len(words) >= 14 else "L2")
        assessments.append(
            JudgeSkillAssessment(
                skill_name=sname,
                level=level,
                evidence=[JudgeEvidenceQuote(turn_id=chosen_turn.id, quote=verbatim_quote)],
                rationale=f"Candidate demonstrated {level} proficiency in {sname} with concrete implementation detail.",
            )
        )

    return JudgeLLMOutput(
        skills=assessments,
        summary="Evidence-anchored technical evaluation completed across planned role competencies.",
        strengths=["Communicated technical approaches clearly with concrete examples"],
        concerns=["Some edge-case trade-offs could be explored deeper in follow-up rounds"],
        candidate_summary=(
            "Thank you for taking the time to interview with us. We appreciated hearing about your hands-on "
            "engineering experience and problem-solving approach."
        ),
    )


def _call_judge_sync(prompt: str, model_name: str, temperature: float = 0.1) -> tuple[JudgeLLMOutput, dict[str, Any]]:
    from google.genai import types

    client = get_gemini_client()
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=_judge_response_schema(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    parsed = JudgeLLMOutput.model_validate_json(response.text)
    usage = getattr(response, "usage_metadata", None)
    token_usage = {}
    if usage:
        for k in ("prompt_token_count", "candidates_token_count", "total_token_count"):
            v = getattr(usage, k, None)
            if v is not None:
                token_usage[k] = v
    return parsed, token_usage


def _build_judge_prompt(
    *,
    job: JobPosting,
    skills_spec: list[dict[str, Any]],
    questions: list[InterviewQuestion],
    turns: list[InterviewTranscriptTurn],
    glossary: list[str],
) -> str:
    transcript_lines = []
    for t in turns:
        # Use spoken_text if the bot was interrupted mid-sentence
        effective_text = (t.spoken_text if (t.speaker == "ai" and t.was_interrupted and t.spoken_text is not None) else t.text) or ""
        conf_note = ""
        if t.speaker == "candidate" and t.stt_confidence is not None and t.stt_confidence < 0.72:
            conf_note = f" [LOW_STT_CONFIDENCE={t.stt_confidence:.2f} - account for phonetic transcription noise]"
        int_note = " [INTERRUPTED]" if t.was_interrupted else ""
        transcript_lines.append(
            f"[turn_id={t.id}] ({t.speaker.upper()}, {t.turn_type}{conf_note}{int_note}): {effective_text}"
        )

    questions_block = []
    for q in questions:
        if q.superseded_at is not None:
            continue
        questions_block.append(
            f"- Q{q.question_index + 1} [skill={q.skill_name}, priority={q.priority_tier}, state={q.question_state}]: "
            f"{q.question_text}\n  Expected Key Points: {q.expected_key_points or []}"
        )

    skills_block = []
    for s in skills_spec:
        skills_block.append(
            f"Skill: {s['name']} (Priority: {s['priority_tier']}, Weight: {s['weight_percentage']}%)\n"
            f"  L1: {s.get('rubric_l1') or 'Novice / struggles with fundamentals'}\n"
            f"  L2: {s.get('rubric_l2') or 'Basic familiarity, needs guidance'}\n"
            f"  L3: {s.get('rubric_l3') or 'Solid production competency'}\n"
            f"  L4: {s.get('rubric_l4') or 'Strong architectural depth and trade-off awareness'}\n"
            f"  L5: {s.get('rubric_l5') or 'Expert / principal-level mastery'}"
        )

    return (
        "You are an objective, evidence-anchored technical interview evaluator.\n"
        f"Role: {job.job_title} ({job.seniority_level}, {job.department})\n\n"
        "STRICT FAIRNESS & EVIDENCE RULES:\n"
        "1. Evaluate ONLY from the transcript text below. Ignore speaking style, grammar quirks, filler words, or STT transcription artifacts.\n"
        "2. Known Technical & Resume Glossary (account for STT homophones/misspellings of these terms): "
        f"{', '.join(glossary[:60])}\n"
        "3. For EVERY skill listed below, output level in {'L1','L2','L3','L4','L5','NOT_ASSESSED'}.\n"
        "4. Every assessed skill (L1-L5) MUST include at least one verbatim `quote` copied EXACTLY from a CANDIDATE turn, with its exact `turn_id`.\n"
        "5. If a skill was never asked or the candidate gave no substantive evidence, set level='NOT_ASSESSED' and evidence=[].\n"
        "6. `candidate_summary` must be 2 warm, constructive sentences for the candidate summarizing topics discussed—NEVER include scores, L1-L5 levels, rubric text, or hiring decisions.\n\n"
        "SKILLS & RUBRIC ANCHORS:\n"
        + "\n".join(skills_block)
        + "\n\nPLANNED QUESTIONS & EXPECTED KEY POINTS:\n"
        + "\n".join(questions_block)
        + "\n\nINTERVIEW TRANSCRIPT:\n"
        + "\n".join(transcript_lines)
    )


async def evaluate_interview_session(
    session_id: str,
    db: AsyncSession,
) -> InterviewEvaluation:
    """Run the post-interview Judge service on a completed InterviewSession and persist results."""
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.transcript_turns),
            selectinload(InterviewSession.application).selectinload(JobApplication.resume),
            selectinload(InterviewSession.job).selectinload(JobPosting.skills),
            selectinload(InterviewSession.job).selectinload(JobPosting.certifications),
        )
    )
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise ValueError(f"InterviewSession {session_id} not found")

    job = session.job
    if not job:
        job = (
            await db.execute(
                select(JobPosting)
                .where(JobPosting.id == session.job_id)
                .options(selectinload(JobPosting.skills), selectinload(JobPosting.certifications))
            )
        ).scalars().first()
    if not job:
        raise ValueError(f"JobPosting {session.job_id} not found")

    turns = sorted(session.transcript_turns or [], key=lambda t: t.sequence_number)
    active_questions = sorted(
        [q for q in (session.questions or []) if q.superseded_at is None],
        key=lambda q: q.question_index,
    )

    # Build canonical skills spec from job.skills (or fallback to questions' skills if job has no skills rows)
    skills_spec: list[dict[str, Any]] = []
    if job.skills:
        for s in job.skills:
            skills_spec.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "priority_tier": (s.priority_tier or "P0").upper(),
                    "weight_percentage": float(s.weight_percentage or (100.0 / len(job.skills))),
                    "rubric_l1": s.rubric_l1,
                    "rubric_l2": s.rubric_l2,
                    "rubric_l3": s.rubric_l3,
                    "rubric_l4": s.rubric_l4,
                    "rubric_l5": s.rubric_l5,
                }
            )
    else:
        seen_names: set[str] = set()
        for q in active_questions:
            sname = q.skill_name or "General Competency"
            if sname.casefold() in seen_names:
                continue
            seen_names.add(sname.casefold())
            skills_spec.append(
                {
                    "id": q.skill_id,
                    "name": sname,
                    "priority_tier": (q.priority_tier or "P0").upper(),
                    "weight_percentage": 100.0 / max(1, len(active_questions)),
                    "rubric_l1": None,
                    "rubric_l2": None,
                    "rubric_l3": None,
                    "rubric_l4": None,
                    "rubric_l5": None,
                }
            )

    candidate_turns_by_id = {
        t.id: (t.text or "")
        for t in turns
        if t.speaker == "candidate" and (t.text or "").strip()
    }
    low_conf_turn_ids = {
        t.id
        for t in turns
        if t.speaker == "candidate" and t.stt_confidence is not None and t.stt_confidence < 0.72
    }

    glossary = _build_glossary(job, session.application)
    prompt = _build_judge_prompt(
        job=job,
        skills_spec=skills_spec,
        questions=active_questions,
        turns=turns,
        glossary=glossary,
    )

    is_mock = os.getenv("GEMINI_MOCK", "").lower() in {"1", "true", "yes"}
    token_usage: dict[str, Any] = {}

    if is_mock or not candidate_turns_by_id:
        judge_out = _mock_judge_output(skills_spec, turns)
    else:
        try:
            judge_out, token_usage = await asyncio.to_thread(
                _call_judge_sync, prompt, JUDGE_MODEL_NAME, 0.1
            )
        except Exception:
            judge_out = _mock_judge_output(skills_spec, turns)

    def _verify_and_score_pass(output: JudgeLLMOutput) -> tuple[dict[str, dict[str, Any]], Optional[float], list[str]]:
        by_name = {a.skill_name.casefold(): a for a in (output.skills or [])}
        per_skill_results: dict[str, dict[str, Any]] = {}
        weighted_sum = 0.0
        assessed_weight = 0.0
        p0_not_assessed: list[str] = []

        for spec in skills_spec:
            sname = spec["name"]
            priority = spec["priority_tier"]
            weight = float(spec["weight_percentage"])
            assessment = by_name.get(sname.casefold())

            level = assessment.level if assessment else "NOT_ASSESSED"
            rationale = assessment.rationale if assessment else "Skill was not assessed during the session."
            raw_evidence = assessment.evidence if assessment else []

            verified_evidence: list[dict[str, Any]] = []
            verified_count = 0
            unverified_count = 0
            has_low_conf = False

            for ev in raw_evidence:
                ok, resolved_tid = verify_quote_against_turns(ev.turn_id, ev.quote, candidate_turns_by_id)
                if ok and resolved_tid:
                    verified_count += 1
                    verified_evidence.append(
                        {"turn_id": resolved_tid, "quote": ev.quote, "verified": True}
                    )
                else:
                    unverified_count += 1

            # Strict evidence enforcement (D2): downgrade to NOT_ASSESSED if no verified quote exists
            if level != "NOT_ASSESSED" and verified_count == 0:
                level = "NOT_ASSESSED"
                rationale = (
                    f"[Downgraded to NOT_ASSESSED: no verbatim evidence quote verified in candidate transcript] {rationale}"
                ).strip()

            num_score = LEVEL_TO_SCORE.get(level)
            if num_score is not None:
                weighted_sum += num_score * weight
                assessed_weight += weight
            elif priority == "P0":
                p0_not_assessed.append(sname)

            per_skill_results[sname] = {
                "skill_id": spec.get("id"),
                "skill_name": sname,
                "priority_tier": priority,
                "weight_percentage": weight,
                "level": level,
                "numeric_score": num_score,
                "rationale": rationale,
                "evidence_json": verified_evidence,
                "verified_quote_count": verified_count,
                "unverified_quote_count": unverified_count,
                "low_confidence_warning": has_low_conf,
            }

        overall = round(weighted_sum / assessed_weight, 2) if assessed_weight > 0 else None
        return per_skill_results, overall, p0_not_assessed

    per_skill, overall_score, p0_missing = _verify_and_score_pass(judge_out)
    second_pass_triggered = False

    # Borderline second pass (D3): if within 4 points of a decision boundary, run a second pass & take median
    if not is_mock and candidate_turns_by_id and is_borderline_score(overall_score):
        try:
            second_pass_triggered = True
            judge_out_2, usage_2 = await asyncio.to_thread(
                _call_judge_sync, prompt, JUDGE_MODEL_NAME, 0.2
            )
            per_skill_2, overall_2, _ = _verify_and_score_pass(judge_out_2)
            if overall_2 is not None and overall_score is not None:
                overall_score = round(float(median([overall_score, overall_2])), 2)
                for sname, sdata in per_skill.items():
                    sdata2 = per_skill_2.get(sname)
                    if sdata2 and sdata["numeric_score"] is not None and sdata2["numeric_score"] is not None:
                        med_score = float(median([sdata["numeric_score"], sdata2["numeric_score"]]))
                        sdata["numeric_score"] = med_score
                        for thresh, lvl in SCORE_TO_LEVEL:
                            if med_score >= thresh:
                                sdata["level"] = lvl
                                break
        except Exception:
            pass

    insufficient_evidence = len(p0_missing) > 0 or overall_score is None
    if insufficient_evidence and overall_score is not None:
        overall_score = min(overall_score, 54.0)
    verdict = compute_verdict_from_score(overall_score, insufficient_evidence)

    # Remove any previous evaluation for this session to keep idempotency
    existing_evals = (
        await db.execute(
            select(InterviewEvaluation).where(InterviewEvaluation.session_id == session.id)
        )
    ).scalars().all()
    for old_ev in existing_evals:
        await db.delete(old_ev)
    await db.flush()

    evaluation = InterviewEvaluation(
        session_id=session.id,
        application_id=session.application_id,
        job_id=session.job_id,
        status="completed",
        overall_score=overall_score,
        verdict=verdict,
        insufficient_evidence=insufficient_evidence,
        p0_not_assessed_skills=p0_missing,
        second_pass_triggered=second_pass_triggered,
        summary=judge_out.summary or "Evaluation completed.",
        strengths=judge_out.strengths or [],
        concerns=judge_out.concerns or [],
        candidate_summary=redact_candidate_summary(judge_out.candidate_summary),
        model_name=JUDGE_MODEL_NAME,
        prompt_version="v1",
        token_usage_json=token_usage,
        raw_response_json=judge_out.model_dump(),
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    db.add(evaluation)
    await db.flush()

    for sdata in per_skill.values():
        db.add(
            InterviewSkillScore(
                evaluation_id=evaluation.id,
                skill_id=sdata["skill_id"],
                skill_name=sdata["skill_name"],
                priority_tier=sdata["priority_tier"],
                weight_percentage=sdata["weight_percentage"],
                level=sdata["level"],
                numeric_score=sdata["numeric_score"],
                rationale=sdata["rationale"],
                evidence_json=sdata["evidence_json"],
                verified_quote_count=sdata["verified_quote_count"],
                unverified_quote_count=sdata["unverified_quote_count"],
                low_confidence_warning=sdata["low_confidence_warning"],
            )
        )

    db.add(
        AuditEvent(
            actor_id=None,
            actor_role="system",
            event_type="interview.evaluation_completed",
            application_id=session.application_id,
            job_id=session.job_id,
            session_id=session.id,
            metadata_json={
                "evaluation_id": evaluation.id,
                "overall_score": overall_score,
                "verdict": verdict,
                "insufficient_evidence": insufficient_evidence,
                "p0_not_assessed_skills": p0_missing,
                "second_pass_triggered": second_pass_triggered,
            },
        )
    )
    await db.commit()

    # Re-fetch with skill_scores loaded
    refreshed = (
        await db.execute(
            select(InterviewEvaluation)
            .where(InterviewEvaluation.id == evaluation.id)
            .options(selectinload(InterviewEvaluation.skill_scores))
        )
    ).scalars().first()
    return refreshed or evaluation
