# Candidly Phase A6.3 — Evaluation Pipeline Follow-ups & Technical Notes

**Date:** October 2026  
**Context:** Phase A6.3 Production Readiness Hardening  
**Scope Note:** The automated evaluation agent, judge scoring, and evaluation prompt pipeline are explicitly **OUT OF SCOPE** for Phase A6.3. This document records the architectural findings, potential race conditions, and recommended design improvements to be addressed when the Evaluator Agent is designed and implemented.

---

## 1. Current State in A6.3

During Phase A6.3, session finalization was centralized in `backend/app/services/interview_v2/finalizer.py`:
- `finalize_interview_session()` provides an entrypoint called by both WebSocket completion (`runner.py`) and REST fallback (`main.py:end_interview_session`).
- It employs a database transaction with row-level locking (`with_for_update()`) on `InterviewSession` to prevent concurrent finalization races.
- If status is already `'completed'`, it safely deduplicates and returns without triggering duplicate evaluations.
- When finalizing, it creates a pending record in `InterviewEvaluation(status="pending")` and schedules background evaluation via `asyncio.create_task(run_evaluation_for_session(session_id))`.
- If database persistence fails during finalization, `runner.py` catches the error, suppresses `SessionEnded`, and emits `SessionError(error="SessionPersistenceFailed", retryable=True)` to the candidate client so that retries or REST fallback can occur.

---

## 2. Identified Gaps & Technical Debt (Deferred to Evaluator Agent Milestone)

### 2.1 Lack of Database-Level Unique Constraint on `interview_evaluations.session_id`
- **Current Observation:** The `interview_evaluations` table allows multiple rows per `session_id` at the database level if concurrent processes bypass row locks or execute independent inserts.
- **Recommended Follow-up:**
  - Add an Alembic migration introducing a `UNIQUE (session_id)` constraint or index on `interview_evaluations`.
  - Handle `IntegrityError` idempotently with an upsert or `ON CONFLICT DO NOTHING` / `select existing` pattern.

### 2.2 In-Memory Background Tasks vs. Durable Distributed Queue
- **Current Observation:** Evaluations are dispatched via `asyncio.create_task(run_evaluation_for_session(session_id))`. If the FastAPI worker process restarts, crashes, or is deployed while an evaluation is running, the in-memory task is dropped. The session remains in `InterviewEvaluation(status="pending")` indefinitely.
- **Recommended Follow-up:**
  - Replace `asyncio.create_task` with a durable background task worker (e.g., Celery, ARQ, or Cloud Tasks).
  - Implement a periodic sweeper / dead-letter reconciliation job that queries for `InterviewEvaluation` records stuck in `status="pending"` for >15 minutes and reenqueues them.

### 2.3 Turn-by-Turn Real-time Scoring vs. Post-Session Batch Evaluation
- **Current Observation:** `turn_evaluator.py` provides turn-level evaluation heuristics, while `_run_evaluation_for_session` performs post-session LLM scoring. The interaction between turn-level data and final session rubric grading is loosely coupled.
- **Recommended Follow-up:**
  - Standardize evaluation provenance: link each turn's transcript, latency, and candidate audio events to the evaluation schema.
  - Implement structured schemas for evaluation rubrics aligned with recruiter-approved blueprints.

### 2.4 Retry Worker & Exponential Backoff for LLM Scoring
- **Current Observation:** If Amazon Bedrock or external LLM providers experience throttling (429) or transient 5xx errors during evaluation, the failure marks the evaluation as failed without automated exponential backoff or retry scheduling.
- **Recommended Follow-up:**
  - Wrap LLM rubric evaluation in an exponential backoff retry policy (with jitter).
  - Provide a manual "Re-run Evaluation" button in the Recruiter Dashboard for failed evaluations.

---

## 3. Summary
The A6.3 delivery ensures that candidates never experience silent database failures and that session state transitions are concurrency-safe. The follow-up tasks above should be prioritized when the dedicated Evaluator Agent milestone begins.
