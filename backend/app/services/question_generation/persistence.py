from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import (
    InterviewGenerationRun,
    InterviewQuestion,
    InterviewSession,
    AuditEvent,
)

from .contracts import GeneratedInterviewPlan, QuestionGenerationSnapshot
from .provider import MODEL_NAME, build_interviewer_brief, generate_questions
from .snapshot import build_snapshot
from .validator import validate_plan


async def generate_for_application(
    application_id: str, db: AsyncSession, force: bool = False
) -> InterviewGenerationRun:
    snapshot, application = await build_snapshot(application_id, db)
    if not force:
        existing_stmt = (
            select(InterviewGenerationRun)
            .where(
                InterviewGenerationRun.application_id == application_id,
                InterviewGenerationRun.input_snapshot_hash == snapshot.input_snapshot_hash,
                InterviewGenerationRun.status == "succeeded",
            )
            .order_by(InterviewGenerationRun.created_at.desc())
        )
        existing = (await db.execute(existing_stmt)).scalars().first()
        if existing:
            return existing

    run = InterviewGenerationRun(
        application_id=application.id,
        job_id=application.job_id,
        status="running",
        model_name=MODEL_NAME,
        prompt_template_version="v1",
        input_snapshot_hash=snapshot.input_snapshot_hash,
        resume_version_used=snapshot.candidate.resume_sha256,
    )
    db.add(run)
    db.add(AuditEvent(
        actor_id=application.candidate_id,
        actor_role="candidate",
        event_type="interview.question_generation_started",
        application_id=application.id,
        job_id=application.job_id,
    ))
    await db.flush()
    try:
        result = await generate_questions(snapshot, application.resume.file_data)
        errors = validate_plan(result.plan, snapshot)
        if errors:
            raise ValueError("; ".join(errors))

        previous_runs_query = select(InterviewGenerationRun.id).where(
            InterviewGenerationRun.application_id == application.id,
            InterviewGenerationRun.status == "succeeded",
        )
        if not force:
            previous_runs_query = previous_runs_query.where(
                InterviewGenerationRun.input_snapshot_hash != snapshot.input_snapshot_hash
            )
        previous_runs = (await db.execute(previous_runs_query)).scalars().all()
        if previous_runs:
            await db.execute(
                update(InterviewQuestion)
                .where(InterviewQuestion.generation_run_id.in_(previous_runs))
                .values(superseded_at=datetime.utcnow())
            )

        rubric_payload = {
            "job_id": application.job_id,
            "competencies": [c.model_dump() for c in snapshot.competencies],
            "duration_minutes": snapshot.job.duration_minutes,
        }
        import hashlib, json
        run.job_rubric_version_used = hashlib.sha256(
            json.dumps(rubric_payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        run.retry_count = result.retry_count
        run.gemini_request_id = result.request_id
        run.token_usage_json = result.token_usage

        brief = build_interviewer_brief(
            snapshot,
            interviewer_tone=getattr(application.job, "interviewer_tone", "") or "",
            pacing_strictness=getattr(application.job, "pacing_strictness", "Balanced") or "Balanced",
        )

        # Reuse scheduled session if force-regenerating before interview starts, else create new
        existing_session_stmt = (
            select(InterviewSession)
            .where(
                InterviewSession.application_id == application.id,
                InterviewSession.status == "scheduled",
            )
            .order_by(InterviewSession.created_at.desc())
        )
        session = (await db.execute(existing_session_stmt)).scalars().first() if force else None
        if session is None:
            session = InterviewSession(
                application_id=application.id,
                job_id=application.job_id,
                status="scheduled",
                total_questions_planned=len(result.plan.questions),
                duration_planned_mins=application.job.interview_duration_mins,
                gemini_model_used=MODEL_NAME,
                system_prompt_snapshot=brief,
                interviewer_brief=brief,
            )
            db.add(session)
            await db.flush()
        else:
            session.total_questions_planned = len(result.plan.questions)
            session.duration_planned_mins = application.job.interview_duration_mins
            session.gemini_model_used = MODEL_NAME
            session.system_prompt_snapshot = brief
            session.interviewer_brief = brief
            await db.flush()

        for generated in result.plan.questions:
            initial_coverage = {
                kp: "uncovered" for kp in (generated.expected_key_points or [])
            }
            db.add(
                InterviewQuestion(
                    session_id=session.id,
                    generation_run_id=run.id,
                    question_index=generated.question_index,
                    skill_id=generated.skill_id,
                    skill_name=generated.skill_name,
                    skill_category=generated.skill_category,
                    priority_tier=generated.priority_tier,
                    question_text=generated.question_text,
                    expected_key_points=generated.expected_key_points,
                    follow_up_depth_allowed=generated.follow_up_depth_allowed,
                    question_state="not_started",
                    coverage_status=initial_coverage,
                    evidence_turn_ids=[],
                )
            )
        run.status = "succeeded"
        run.completed_at = datetime.utcnow()
        db.add(AuditEvent(
            actor_id=application.candidate_id,
            actor_role="candidate",
            event_type="interview.question_generation_succeeded",
            application_id=application.id,
            job_id=application.job_id,
            metadata_json={"question_count": len(result.plan.questions), "force": force},
        ))
        await db.commit()
        await db.refresh(run)
        return run
    except Exception as exc:
        run.status = "failed"
        run.failure_reason = str(exc)
        run.completed_at = datetime.utcnow()
        db.add(AuditEvent(
            actor_id=application.candidate_id,
            actor_role="candidate",
            event_type="interview.question_generation_failed",
            status="failed",
            application_id=application.id,
            job_id=application.job_id,
        ))
        await db.commit()
        raise

