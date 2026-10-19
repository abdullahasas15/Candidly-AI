"""Runtime Interview Plan Materializer (Checkpoint R3.3).

Pins approved blueprint_id and version to the session.
Materializes structured InterviewQuestion rows for each section:
- welcome (spoken agenda)
- intro_hook (personalized opening from CandidatePersonalization)
- skill sections (ordered P0 -> P1 -> P2):
    - anchor
    - anchor_alt
    - escalation
    - probes (from blueprint questions)
    - resume_probe (from candidate personalization, if candidate has resume evidence for that skill)
- candidate_qa (Q&A wrap-up)
- closing (standard wrap-up)

Initializes:
- session_expectation_coverage for all blueprint expectations with status='not_probed'
- interview_sessions.runtime_state (phase, current_section_index, section_state, pacing)
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def clean_role_title_for_speech(role: Optional[str]) -> str:
    """Normalize role titles for spoken text so hyphens/dashes are never spoken as 'minus' (e.g. 'SDE -1' -> 'Software Development Engineer 1')."""
    if not role:
        return "Software Engineer"
    cleaned = str(role)
    cleaned = re.sub(r"\s*[\-–—_]+\s*", " ", cleaned).strip()
    cleaned = re.sub(r"\bSDE\s*I\b", "Software Development Engineer 1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*II\b", "Software Development Engineer 2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*III\b", "Software Development Engineer 3", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*1\b", "Software Development Engineer 1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*2\b", "Software Development Engineer 2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*3\b", "Software Development Engineer 3", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\b", "Software Development Engineer", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSWE\b", "Software Engineer", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

from backend.app.models import (
    InterviewSession,
    InterviewQuestion,
    InterviewBlueprint,
    BlueprintSection,
    BlueprintExpectation,
    BlueprintQuestion,
    CandidatePersonalization,
    SessionExpectationCoverage,
    JobPosting,
    JobApplication,
)

logger = logging.getLogger(__name__)


async def materialize_blueprint_session_plan(
    session: InterviewSession,
    db: AsyncSession,
) -> bool:
    """Materialize the runtime question plan from the job's active approved blueprint.

    Returns True if plan was materialized from an approved blueprint,
    or False if this is a legacy session without a blueprint.
    """
    # 1. Load Job
    job_stmt = select(JobPosting).where(JobPosting.id == session.job_id)
    job_res = await db.execute(job_stmt)
    job = job_res.scalar_one_or_none()
    if not job or not job.active_blueprint_id:
        logger.info("Session %s has no active job blueprint; operating in legacy session mode", session.id)
        return False

    # 2. Load Active Blueprint with Sections, Expectations, and Questions
    bp_stmt = (
        select(InterviewBlueprint)
        .where(InterviewBlueprint.id == job.active_blueprint_id)
    )
    bp_res = await db.execute(bp_stmt)
    blueprint = bp_res.scalar_one_or_none()
    if not blueprint:
        logger.warning("Active blueprint %s not found for job %s", job.active_blueprint_id, job.id)
        return False

    # Pin blueprint_id and version
    session.blueprint_id = blueprint.id
    session.blueprint_version = blueprint.version or 1

    # Load all sections
    sec_stmt = (
        select(BlueprintSection)
        .where(BlueprintSection.blueprint_id == blueprint.id)
        .order_by(BlueprintSection.order_index)
        .options(
            selectinload(BlueprintSection.expectations),
            selectinload(BlueprintSection.questions),
        )
    )
    sec_res = await db.execute(sec_stmt)
    sections = sec_res.scalars().all()

    # 3. Load Candidate Personalization if available
    cp_stmt = select(CandidatePersonalization).where(CandidatePersonalization.application_id == session.application_id)
    cp_res = await db.execute(cp_stmt)
    personalization = cp_res.scalar_one_or_none()

    intro_hook_text = (
        personalization.intro_hook
        if personalization and personalization.intro_hook
        else "Could you briefly introduce yourself and share what interests you most about this role?"
    )
    personalization_probes = (
        personalization.per_skill_probes
        if personalization and isinstance(personalization.per_skill_probes, dict)
        else {}
    )

    # 4. Materialize Questions
    q_index = 0
    all_coverages = []
    pacing_sections = []

    # Welcome Section (spoken agenda template, zero LLM)
    welcome_sec = next((s for s in sections if s.section_type == "welcome"), None)
    spoken_agenda = [
        getattr(s, "spoken_topic_label", None) or s.skill_name or s.title
        for s in sections
        if s.section_type == "skill"
    ]
    agenda_str = ", ".join(spoken_agenda[:-1]) + f", and {spoken_agenda[-1]}" if len(spoken_agenda) > 1 else (spoken_agenda[0] if spoken_agenda else "technical topics")
    job_role_title = getattr(job, "job_title", None) or getattr(job, "title", "the position")
    clean_job_title = clean_role_title_for_speech(job_role_title)
    welcome_text = (
        f"Hi there! Welcome to your interview for the {clean_job_title} role. "
        f"Today we will cover {agenda_str}, followed by time for any questions you have for us. "
        "Does that sound good to you?"
    )

    db.add(
        InterviewQuestion(
            session_id=session.id,
            question_index=q_index,
            skill_name="Welcome & Agenda",
            skill_category="Administrative",
            priority_tier="P0",
            question_text=welcome_text,
            kind="welcome",
            section_id=welcome_sec.id if welcome_sec else None,
            question_state="queued",
            expected_key_points=["Candidate acknowledges readiness to proceed"],
        )
    )
    q_index += 1

    # Intro Section: Always static as explicitly requested by candidate/recruiter workflow
    intro_sec = next((s for s in sections if s.section_type == "intro"), None)
    static_intro_question = (
        "To start off, could you please introduce yourself, tell me about your background, and share some highlights from your key projects and experiences?"
    )
    db.add(
        InterviewQuestion(
            session_id=session.id,
            question_index=q_index,
            skill_name="Introduction",
            skill_category="Background",
            priority_tier="P0",
            question_text=static_intro_question,
            kind="intro_hook",
            section_id=intro_sec.id if intro_sec else None,
            personalization_context={"source": "static_standard_intro"},
            question_state="queued",
            expected_key_points=["Candidate self-introduction", "Relevant project background", "Technical experience highlights"],
        )
    )
    q_index += 1

    # Skill Sections (P0 -> P1 -> P2 order preserved by blueprint order_index)
    skill_sections = [s for s in sections if s.section_type == "skill"]
    for s in skill_sections:
        s_name = s.skill_name or s.title
        tier = s.priority_tier or "P0"
        s_exps = s.expectations or []
        exp_id_map = {e.order_index: e.id for e in s_exps}

        # Initialize SessionExpectationCoverage for every expectation
        for e in s_exps:
            all_coverages.append(
                SessionExpectationCoverage(
                    session_id=session.id,
                    expectation_id=e.id,
                    status="not_probed",
                    evidence_turn_ids=[],
                    evidence_quote=None,
                )
            )

        # Separate questions by role
        anchor_q = next((q for q in s.questions if q.question_role == "anchor"), None)
        alt_q = next((q for q in s.questions if q.question_role == "anchor_alt"), None)
        esc_q = next((q for q in s.questions if q.question_role == "escalation"), None)
        probes = [q for q in s.questions if q.question_role == "probe"]

        # Anchor
        if anchor_q:
            db.add(
                InterviewQuestion(
                    session_id=session.id,
                    question_index=q_index,
                    skill_name=s_name,
                    skill_category=getattr(s, "skill_category", "Technical") or "Technical",
                    priority_tier=tier,
                    question_text=anchor_q.question_text,
                    section_id=s.id,
                    blueprint_question_id=anchor_q.id,
                    kind="anchor",
                    target_expectation_ids=[exp_id_map.get(idx, idx) for idx in (anchor_q.target_expectation_ids or [0])],
                    question_state="queued",
                    expected_key_points=[e.expectation_text for e in s_exps if getattr(e, "importance", "core") == "core"],
                )
            )
            q_index += 1

        # Anchor Alt
        if alt_q:
            db.add(
                InterviewQuestion(
                    session_id=session.id,
                    question_index=q_index,
                    skill_name=s_name,
                    skill_category=getattr(s, "skill_category", "Technical") or "Technical",
                    priority_tier=tier,
                    question_text=alt_q.question_text,
                    section_id=s.id,
                    blueprint_question_id=alt_q.id,
                    kind="anchor_alt",
                    personalization_context={"trigger_condition": alt_q.trigger_condition},
                    target_expectation_ids=[exp_id_map.get(idx, idx) for idx in (alt_q.target_expectation_ids or [0])],
                    question_state="queued",
                )
            )
            q_index += 1

        # Escalation
        if esc_q:
            db.add(
                InterviewQuestion(
                    session_id=session.id,
                    question_index=q_index,
                    skill_name=s_name,
                    skill_category=getattr(s, "skill_category", "Technical") or "Technical",
                    priority_tier=tier,
                    question_text=esc_q.question_text,
                    section_id=s.id,
                    blueprint_question_id=esc_q.id,
                    kind="escalation",
                    target_expectation_ids=[exp_id_map.get(idx, idx) for idx in (esc_q.target_expectation_ids or [0])],
                    question_state="queued",
                )
            )
            q_index += 1

        # Blueprint Probes
        for p in probes:
            db.add(
                InterviewQuestion(
                    session_id=session.id,
                    question_index=q_index,
                    skill_name=s_name,
                    skill_category=getattr(s, "skill_category", "Technical") or "Technical",
                    priority_tier=tier,
                    question_text=p.question_text,
                    section_id=s.id,
                    blueprint_question_id=p.id,
                    kind="probe",
                    personalization_context={"trigger_condition": p.trigger_condition},
                    target_expectation_ids=[exp_id_map.get(idx, idx) for idx in (p.target_expectation_ids or [])],
                    question_state="queued",
                )
            )
            q_index += 1

        # Personalized Resume Probe (R3.2)
        probe_for_skill = None
        if isinstance(personalization_probes, dict):
            probe_for_skill = (
                personalization_probes.get(s.skill_id)
                or personalization_probes.get(s.id)
                or personalization_probes.get(s_name)
            )

        if probe_for_skill:
            db.add(
                InterviewQuestion(
                    session_id=session.id,
                    question_index=q_index,
                    skill_name=s_name,
                    skill_category=getattr(s, "skill_category", "Technical") or "Technical",
                    priority_tier=tier,
                    question_text=probe_for_skill,
                    section_id=s.id,
                    kind="resume_probe",
                    personalization_context={
                        "source": "candidate_resume",
                        "claims_to_verify": getattr(personalization, "claims_to_verify", []),
                    },
                    target_expectation_ids=[s_exps[0].id] if s_exps else [],
                    question_state="queued",
                )
            )
            q_index += 1

    # Candidate Q&A Section
    qa_sec = next((s for s in sections if s.section_type == "candidate_qa"), None)
    db.add(
        InterviewQuestion(
            session_id=session.id,
            question_index=q_index,
            skill_name="Candidate Q&A",
            skill_category="Wrap-Up",
            priority_tier="P0",
            question_text="Now I would love to open up the floor to you. What questions or suggestions do you have for us regarding the team, our technical stack, or this role?",
            kind="candidate_qa",
            section_id=qa_sec.id if qa_sec else None,
            question_state="queued",
        )
    )
    q_index += 1

    # Closing Section
    close_sec = next((s for s in sections if s.section_type == "closing"), None)
    db.add(
        InterviewQuestion(
            session_id=session.id,
            question_index=q_index,
            skill_name="Closing",
            skill_category="Administrative",
            priority_tier="P0",
            question_text="Thank you so much for taking the time to speak with me today. Our team will review your session and be in touch with next steps shortly. Have a wonderful rest of your day!",
            kind="closing",
            section_id=close_sec.id if close_sec else None,
            question_state="queued",
        )
    )
    q_index += 1

    # Add all expectation coverage records
    for cov in all_coverages:
        db.add(cov)

    # 5. Initialize session runtime_state
    session.total_questions_planned = q_index
    session.duration_planned_mins = getattr(blueprint, "total_duration_mins", None) or getattr(blueprint, "duration_mins", None) or session.duration_planned_mins or 30

    runtime_state = {
        "phase": "welcome",
        "current_section_index": 0,
        "total_sections": len(sections),
        "section_state": "pending",
        "active_anchor_kind": "anchor",
        "used_anchor_alt": False,
        "active_probes_asked": [],
        "follow_up_count_in_section": 0,
        "section_start_timestamp": None,
        "pacing": {
            "total_duration_mins": session.duration_planned_mins,
            "sections": [
                {
                    "section_index": s.order_index,
                    "section_id": s.id,
                    "section_type": s.section_type,
                    "skill_name": s.skill_name or s.title,
                    "priority_tier": s.priority_tier,
                    "allocated_minutes": s.allocated_minutes,
                    "spoken_topic_label": getattr(s, "spoken_topic_label", None) or s.skill_name or s.title,
                }
                for s in sections
            ],
        },
    }
    session.runtime_state = runtime_state

    logger.info(
        "Materialized runtime plan for session %s from blueprint %s (v%s): %d questions across %d sections",
        session.id, blueprint.id, blueprint.version, q_index, len(sections),
    )
    return True
