"""Shared session finalization service for Interview V2 and REST endpoints.

Guarantees:
1. Exactly-once evaluation scheduling: uses row-level locking (with_for_update)
   and a pending InterviewEvaluation placeholder to prevent duplicate triggers
   across WebSocket runner termination and REST /end fallback.
2. Atomicity: interview session status, job application status, audit event,
   and evaluation record are committed in a single transaction.
3. Safe persistence: raises SessionPersistenceError on DB commit failure so callers
   never report false terminal success to clients.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import BackgroundTasks
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    AuditEvent,
    InterviewEvaluation,
    InterviewSession,
    JobApplication,
    User,
)
from backend.app.services.interview.turn_evaluator import evaluate_interview_session

logger = logging.getLogger(__name__)


class SessionPersistenceError(Exception):
    """Raised when interview session finalization fails to commit to the database."""
    pass


async def run_evaluation_for_session(session_id: str) -> None:
    """Run post-interview Judge evaluation off-request when a session completes."""
    try:
        async with AsyncSessionLocal() as session:
            await evaluate_interview_session(session_id, session)
            await session.commit()
            logger.info("Successfully evaluated interview session %s", session_id)
    except Exception:
        logger.exception("Post-interview evaluation failed for session %s", session_id)


async def _finalize_session_in_db(
    session_id: str,
    db: AsyncSession,
    *,
    ended_by: Optional[str] = None,
    current_user: Optional[User] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> dict[str, Any]:
    """Execute finalization transaction on the provided DB session."""
    # 1. Acquire row lock on InterviewSession to serialize concurrent terminal paths
    stmt = (
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .with_for_update()
    )
    res = await db.execute(stmt)
    if hasattr(res, "scalar_one_or_none"):
        session = res.scalar_one_or_none()
        if asyncio.iscoroutine(session):
            session = await session
    else:
        session = None

    if session is None:
        logger.warning("InterviewSession %s not found in DB during finalization", session_id)
        return {
            "status": "completed",
            "session_id": session_id,
            "application_id": None,
            "already_completed": False,
            "evaluation_scheduled": False,
            "message": f"InterviewSession {session_id} not found in database.",
        }

    is_already_completed = (session.status == "completed")
    should_schedule_eval = False

    # 2. Mark session and application completed if not already completed
    if not is_already_completed:
        session.status = "completed"
        session.current_phase = "completed"
        if not session.completed_at:
            session.completed_at = datetime.utcnow()

        if not session.is_practice and session.application_id:
            await db.execute(
                update(JobApplication)
                .where(JobApplication.id == session.application_id)
                .values(status="interview_completed")
            )

        # Record audit event
        actor_email = ended_by or (current_user.email if current_user else "candidate")
        db.add(
            AuditEvent(
                actor_id=current_user.id if current_user else None,
                actor_role=current_user.role if current_user else None,
                event_type="interview.ended",
                status="success",
                job_id=session.job_id,
                application_id=session.application_id,
                session_id=session.id,
                metadata_json={"ended_by": actor_email},
            )
        )

    # 3. Schedule evaluation exactly once for non-practice sessions
    if not session.is_practice:
        eval_stmt = select(InterviewEvaluation.id).where(InterviewEvaluation.session_id == session.id)
        existing_eval = (await db.execute(eval_stmt)).scalars().first()
        if not existing_eval:
            # Insert pending evaluation placeholder to lock out duplicate evaluations
            placeholder = InterviewEvaluation(
                session_id=session.id,
                application_id=session.application_id,
                job_id=session.job_id,
                status="pending",
                created_at=datetime.utcnow(),
            )
            db.add(placeholder)
            should_schedule_eval = True

    # 4. Commit transaction atomically
    await db.commit()

    # 5. Schedule background evaluation task only after successful commit
    if should_schedule_eval:
        if background_tasks is not None:
            background_tasks.add_task(run_evaluation_for_session, session.id)
        else:
            asyncio.create_task(run_evaluation_for_session(session.id))

    return {
        "status": "completed",
        "session_id": session.id,
        "application_id": session.application_id,
        "already_completed": is_already_completed,
        "evaluation_scheduled": should_schedule_eval,
        "message": (
            "Interview session already completed."
            if is_already_completed
            else "Interview session ended and marked as completed."
        ),
    }


async def finalize_interview_session(
    session_id: str,
    *,
    ended_by: Optional[str] = None,
    current_user: Optional[User] = None,
    db: Optional[AsyncSession] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> dict[str, Any]:
    """Finalize an interview session idempotently with exactly-once evaluation scheduling.

    Can be called with an active db session or will manage its own AsyncSessionLocal context.
    Raises SessionPersistenceError if the database commit fails.
    """
    if db is not None:
        try:
            return await _finalize_session_in_db(
                session_id,
                db,
                ended_by=ended_by,
                current_user=current_user,
                background_tasks=background_tasks,
            )
        except Exception as err:
            try:
                await db.rollback()
            except Exception:
                pass
            logger.error("Database commit error finalizing session %s: %s", session_id, err, exc_info=True)
            raise SessionPersistenceError(f"Failed to persist finalization for session {session_id}: {err}") from err

    async with AsyncSessionLocal() as session_db:
        try:
            return await _finalize_session_in_db(
                session_id,
                session_db,
                ended_by=ended_by,
                current_user=current_user,
                background_tasks=background_tasks,
            )
        except Exception as err:
            try:
                await session_db.rollback()
            except Exception:
                pass
            logger.error("Database commit error finalizing session %s: %s", session_id, err, exc_info=True)
            raise SessionPersistenceError(f"Failed to persist finalization for session {session_id}: {err}") from err
