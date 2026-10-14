#!/usr/bin/env python3
"""Print Interview Script CLI (Checkpoint R3.6).

Usage:
    PYTHONPATH=. python scripts/print_interview_script.py <session_id>

Outputs a clean, human-readable interview execution transcript with:
- Session metadata (ID, candidate, job, blueprint version, timing)
- Structured questions by section (Welcome, Intro, Skill Anchors/Alts/Escalations/Probes, Q&A, Closing)
- Spoken dialogue turns with latency instrumentation and provider tracking
- Final expectation coverage status
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    InterviewSession,
    InterviewQuestion,
    InterviewTranscriptTurn,
    SessionExpectationCoverage,
    BlueprintExpectation,
    BlueprintSection,
)


async def print_script(session_id: str) -> None:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(InterviewSession)
            .where(InterviewSession.id == session_id)
            .options(
                selectinload(InterviewSession.application),
                selectinload(InterviewSession.job),
                selectinload(InterviewSession.blueprint),
                selectinload(InterviewSession.questions),
                selectinload(InterviewSession.transcript_turns),
                selectinload(InterviewSession.expectation_coverages).selectinload(SessionExpectationCoverage.expectation),
            )
        )
        res = await db.execute(stmt)
        sess = res.scalar_one_or_none()
        if not sess:
            print(f"Error: Session '{session_id}' not found.")
            sys.exit(1)

        app = sess.application
        job = sess.job
        bp = sess.blueprint

        job_title = (getattr(job, "job_title", None) or getattr(job, "title", "Unknown Role")) if job else "Unknown Role"
        print("=" * 80)
        print(f"INTERVIEW SCRIPT: {job_title}")
        print("=" * 80)
        print(f"Session ID:         {sess.id}")
        print(f"Candidate:          {app.full_name if app else 'Unknown'} ({app.email if app else 'N/A'})")
        print(f"Status:             {sess.status.upper()}")
        print(f"Planned Duration:   {sess.duration_planned_mins} minutes")
        print(f"Blueprint ID:       {sess.blueprint_id or 'Legacy (No Blueprint)'} (Version {sess.blueprint_version or 'N/A'})")
        print(f"Started At:         {sess.started_at or 'Not started'}")
        print(f"Completed At:       {sess.completed_at or 'In progress'}")
        print("-" * 80)

        # 1. Materialized Plan Questions
        print("\n--- MATERIALIZED RUNTIME QUESTION PLAN ---")
        questions = sorted(sess.questions, key=lambda q: q.question_index)
        if not questions:
            print("  (No questions materialized)")
        else:
            for q in questions:
                kind_badge = f"[{q.kind.upper()}]" if q.kind else "[QUESTION]"
                tier_badge = f"({q.priority_tier})" if q.priority_tier else ""
                print(f"  #{q.question_index + 1:<2} {kind_badge:<14} {q.skill_name or ''} {tier_badge}")
                print(f"      Text:    \"{q.question_text}\"")
                if q.personalization_context:
                    print(f"      Context: {q.personalization_context}")
                print(f"      State:   {q.question_state}")
                print()

        # 1b. Section Exit Reasons & Coverage Status (R3.1 Requirement 5)
        if sess.runtime_state and isinstance(sess.runtime_state, dict) and "sections" in sess.runtime_state:
            print("\n--- SECTION EXECUTION, EXIT REASONS & COVERAGE ---")
            sec_dict = sess.runtime_state.get("sections", {})
            covs_by_sec = {}
            for cov in (sess.expectation_coverages or []):
                s_id = getattr(cov.expectation, "section_id", None)
                if s_id:
                    covs_by_sec.setdefault(s_id, []).append(cov)

            for sec_id, info in sec_dict.items():
                s_name = info.get("skill_name", "Unknown Skill")
                tier = info.get("priority_tier", "P0")
                exit_r = info.get("exit_reason", "in_progress")
                sec_covs = covs_by_sec.get(sec_id, [])
                core_covs = [c for c in sec_covs if getattr(c.expectation, "importance", "core") == "core"]
                core_covered = sum(1 for c in core_covs if c.status in ("covered", "demonstrated", "probed"))
                total_core = len(core_covs)
                cov_stat = f"{core_covered}/{total_core} core probed/covered" if total_core > 0 else "all core covered"
                print(f"  * Section: {s_name:<28} ({tier:<2}) -> Exit Reason: {exit_r:<14} | Coverage: {cov_stat}")
            
            probe_traces = sess.runtime_state.get("probe_traces", [])
            if probe_traces:
                print("\n--- SERVER-SIDE PROBE SELECTION TRACES ---")
                for pt in probe_traces:
                    print(f"  [PROBE TRACE] {pt.get('skill_name')}: action={pt.get('action')} probe_id={pt.get('selected_probe_id')} reason='{pt.get('reasoning')}'")
            print()

        # 2. Spoken Transcript Turns (Full dialogue, no ellipses)
        print("\n--- SPOKEN INTERVIEW DIALOGUE ---")
        turns = sorted(sess.transcript_turns, key=lambda t: t.sequence_number)
        if not turns:
            print("  (No turns recorded yet)")
        else:
            for t in turns:
                speaker_tag = "[AI INTERVIEWER]" if t.speaker == "ai" else f"[{app.full_name if app else 'CANDIDATE'}]"
                latency_info = []
                if t.llm_ttft_ms is not None:
                    latency_info.append(f"TTFT: {t.llm_ttft_ms:.0f}ms")
                if t.total_response_ms is not None:
                    latency_info.append(f"Total: {t.total_response_ms:.0f}ms")
                if t.provider:
                    latency_info.append(f"Provider: {t.provider}")
                latency_str = f" ({', '.join(latency_info)})" if latency_info else ""
                print(f"  Turn #{t.sequence_number:<2} {speaker_tag}{latency_str}")
                print(f"    \"{t.text}\"")
                print()

        # 3. Expectation Coverage Summary
        print("\n--- EXPECTATION COVERAGE SUMMARY ---")
        coverages = sess.expectation_coverages
        if not coverages:
            print("  (No expectation coverages tracked)")
        else:
            for c in coverages:
                exp = c.expectation
                exp_text = exp.expectation_text if exp else "Unknown Expectation"
                imp = getattr(exp, "importance", "core")
                status_icon = "✓" if c.status == "covered" else ("~" if c.status == "partial" else "○")
                print(f"  {status_icon} [{c.status.upper():<10}] ({imp}) {exp_text}")
                if c.evidence_quote:
                    print(f"      Quote: \"{c.evidence_quote}\"")
        print("=" * 80)


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/print_interview_script.py <session_id>")
        sys.exit(1)
    session_id = sys.argv[1].strip()
    asyncio.run(print_script(session_id))


if __name__ == "__main__":
    main()
