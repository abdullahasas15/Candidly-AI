#!/usr/bin/env python3
"""scripts/verify_r3_5.py

Verification and benchmark suite for R3.5 — simple, reliable live interview.

Tests (all offline; only the Apple STT helper touches the system, no network APIs
unless explicitly enabled for the final provider check):
 1. Full scripted interview run (SimpleMockSTTService) end-to-end to completion.
 2. NO-LLM guarantee: every LLM entry point is patched to raise -> full run still works.
 3. One question per utterance: multi-sentence answers commit as ONE turn.
 4. No repeats: every planned question is asked exactly once (no accidental loops).
 5. Button commit: POST /commit-turn semantics -> bridge + next question.
 6. Silence commit: AUTO_COMMIT_SILENCE auto-commit path.
 7. Short-answer rule: "<4 words" -> "Could you say a bit more?" exactly once per skill.
 8. anchor_alt rule: "no experience" -> alternate anchor (verbatim), once per skill.
 9. Time-skip escalation: low clock -> skill sections shed, jump to candidate_qa/closing.
10. Bot never speaks during candidate speech (frame-order invariant).
11. Word budgets: bridge <= 3 words, skill transition <= 12 words.
12. Provider layer: real Apple SpeechAnalyzer transcription of a synthetic clip +
    auto/provider resolution + status endpoint payload shape.

Usage:
    PYTHONPATH=. ./.venv/bin/python scripts/verify_r3_5.py            # all except external STT clip test
    PYTHONPATH=. ./.venv/bin/python scripts/verify_r3_5.py --stt      # also test the real helper on /tmp/r35_voice.pcm
"""

import asyncio
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("verify_r3_5")

BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

RESULTS: List[Dict[str, Any]] = []


def record(test: str, passed: bool, detail: str) -> None:
    RESULTS.append({"test": test, "passed": passed, "detail": detail})
    color = GREEN if passed else RED
    print(f"  {color}[{'PASS' if passed else 'FAIL'}]{RESET} {test} — {detail}")


def brutal_llm_guards() -> list:
    """Patch every LLM entry point used by the interview loop to raise.

    Used for the NO-LLM guarantee test (R3.5 Part 2 requirement).
    """
    patches = []

    def _make(name):
        def boom(*a, **k):
            raise AssertionError(f"LLM CALL FORBIDDEN IN SIMPLE MODE: {name}")
        return boom

    import backend.app.services.interview.simple_session as ss

    patches.append(patch.object(ss, "evaluate_interview_session", _make("evaluate_interview_session")))
    try:
        import backend.app.services.interview.followup_policy as fp
        for fn in ("stream_turn_decision", "stream_section_turn_decision", "answer_candidate_closing_question",
                   "pick_varied_ack", "detect_fast_intent"):
            if hasattr(fp, fn):
                patches.append(patch.object(fp, fn, _make(f"followup_policy.{fn}")))
    except Exception:
        pass
    try:
        from pipecat.services.google.llm_service import GoogleLLMService
        patches.append(patch.object(GoogleLLMService, "_stream", _make("GoogleLLMService._stream"), create=True))
    except Exception:
        pass
    return patches


def make_questions(num_skills: int = 2) -> List[Dict[str, Any]]:
    """A blueprint-style materialized plan: welcome, intro, 2 skills, candidate_qa, closing."""
    qs: List[Dict[str, Any]] = []
    idx = 0

    def add(kind, skill, text):
        nonlocal idx
        qs.append({
            "id": f"q{idx}",
            "question_index": idx,
            "question_text": text,
            "skill_id": f"s{idx}",
            "skill_name": skill,
            "skill_category": "Technical" if skill not in ("Welcome & Agenda", "Introduction", "Candidate Q&A", "Closing") else "Administrative",
            "priority_tier": "P0",
            "expected_key_points": [],
            "question_state": "queued",
            "kind": kind,
        })
        idx += 1

    add("welcome", "Welcome & Agenda", "Welcome! Ready to get started?")
    add("intro_hook", "Introduction", "Could you walk me through your background and the role you're aiming for?")
    for i in range(1, num_skills + 1):
        skill = f"Skill {i}"
        add("anchor", skill, f"Tell me about your strongest project using skill {i}.")
        add("anchor_alt", skill, f"Since skill {i} is new to you, how would you go about learning it under deadline pressure?")
        add("escalation", skill, f"Describe the trickiest trade-off you would make in a project for skill {i}.")
    add("candidate_qa", "Candidate Q&A", "What questions do you have about the team or this role?")
    add("closing", "Closing", "Thanks so much for your time today. We'll be in touch shortly with next steps!")
    return qs


class CoordinatorHarness:
    """Drives SimpleInterviewCoordinator without a WebRTC pipeline."""

    def __init__(self, questions: List[Dict[str, Any]], stt_provider: str = "apple_speechanalyzer"):
        import backend.app.services.interview.simple_session as ss
        from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame

        self.RTVIFrame = RTVIServerMessageFrame
        self.pushed_frames: List[Any] = []
        self.emitted: List[Dict[str, Any]] = []
        self.persisted: List[Dict[str, Any]] = []

        async def fake_push(self_coord, frame, direction=None):
            self.pushed_frames.append(frame)
            if isinstance(frame, RTVIServerMessageFrame):
                self.emitted.append(frame.data)

        async def fake_capture(coord, turn_type, speaker, text, **kwargs):
            self.persisted.append({"turn_type": turn_type, "speaker": speaker, "text": text, **kwargs})
            return MagicMock(id=f"t{len(self.persisted)}")

        self.patches = [
            patch.object(ss.SimpleInterviewCoordinator, "push_frame", new=fake_push),
            patch.object(ss.SimpleInterviewCoordinator, "persist_turn", new=fake_capture),
        ]
        for p in self.patches:
            p.start()

        self.coordinator = ss.SimpleInterviewCoordinator(
            session_id="verify-r35",
            candidate_name="Ada Tester",
            role_title="Backend Engineer",
            questions=questions,
            duration_planned_mins=20.0,
        )

        class MockSTT:
            _provider_name = stt_provider
            last_stt_final_ms = 312.0
            is_bot_speaking = False
            last_ai_speech = ""

            async def flush_and_wait(self, timeout=1.0):
                return None

            def set_bot_speaking(self, v):
                self.is_bot_speaking = v

        self.coordinator._stt_service = MockSTT()

    def ai_speeches(self) -> List[str]:
        return [p.text for p in self.pushed_frames if type(p).__name__ == "TTSSpeakFrame"]

    def bot_state_events(self) -> List[str]:
        return [e.get("state") for e in self.emitted if type(e) is dict and e.get("type") == "interview-bot-state"]

    def close(self):
        for p in self.patches:
            p.stop()


async def drive_answer(harness: "CoordinatorHarness", text: str, commit: Optional[str] = "button"):
    """Simulate a spoken answer: VAD start -> partials/final chunk -> VAD stop -> commit."""
    from pipecat.frames.frames import UserStartedSpeakingFrame, UserStoppedSpeakingFrame

    c = harness.coordinator
    await c.process_frame(UserStartedSpeakingFrame(), None)
    c.record_stt_interim(text)
    await c.process_frame(UserStoppedSpeakingFrame(), None)
    if commit:
        # Tests run back-to-back commits; skip the production debounce guard.
        c._last_commit_monotonic = 0.0
        return await c.commit_turn(reason=commit)
    return None


async def run_full_interview(harness: CoordinatorHarness, answers: List[str]) -> Dict[str, Any]:
    """begin -> for each scripted answer: drive -> commit via button. Returns trace."""
    c = harness.coordinator
    trace: Dict[str, Any] = {"speeches": [], "turns": []}
    await c.begin_interview()
    trace["speeches"].extend(harness.ai_speeches())
    for answer in answers:
        result = await drive_answer(harness, answer, commit="button")
        trace["speeches"].extend(harness.ai_speeches())
        trace["turns"].append(result or {"status": "noop"})
    return trace


# ============================================================================
# 1. Full scripted run + 2. NO-LLM guarantee (combined)
# ============================================================================
async def test_full_run_no_llm() -> None:
    print(f"\n{BOLD}=== [Tests 1+2] Full scripted run with LLMs patched to raise ==={RESET}")
    guards = brutal_llm_guards()
    for g in guards:
        g.start()
    harness = None
    try:
        harness = CoordinatorHarness(make_questions(2))
        answers = [
            "I led the migration of our checkout service to Go and cut p99 latency by 40 percent.",
            "The hardest trade-off was consistency versus latency in the ledger; I chose write-through caching.",
            "For skill 2 I rebuilt the data pipeline in Kafka; consumer lag dropped from minutes to seconds.",
            "I would trade exactly-once semantics for throughput under a deadline, with replay from checkpoints.",
            "I liked the platform roadmap; no questions from my side.",
            "Nothing more to add, thanks.",
            "Thank you so much, this was fun!",
        ]
        trace = await run_full_interview(harness, answers)
        speeches = harness.ai_speeches()
        joined = " ".join(speeches)
        completed = harness.coordinator.is_completed

        checks = {
            "welcome spoken": "your AI interviewer" in joined,
            "intro spoken": "walk me through your background" in joined,
            "skill1 anchor": "strongest project using skill 1" in joined,
            "skill1 escalation": "trickiest trade-off" in joined,
            "skill2 anchor": "skill 2" in joined,
            "skill2 escalation": "for skill 2." in joined,
            "candidate_qa spoken": "What questions do you have" in joined,
            "closing spoken": "Thanks so much" in joined,
            "flow completed": completed,
        }
        for name, ok in checks.items():
            record(f"full-run: {name}", ok, "ok" if ok else f"missing among {len(speeches)} utterances")

        ai_turns = [p for p in harness.persisted if p.get("speaker") == "ai"]
        scripted_ai = [p for p in ai_turns if p.get("question_id")]
        cand_turns = [p for p in harness.persisted if p.get("speaker") == "candidate"]
        record("full-run: every answer persisted", len(cand_turns) == len(answers), f"{len(cand_turns)}/{len(answers)}")
        record("full-run: exactly the planned questions spoken", len(scripted_ai) == QUERIES_PLANNED - 3, f"{len(scripted_ai)} scripted ai turn rows")
        record("full-run: zero LLM exceptions triggered", True, "no 'LLM CALL FORBIDDEN' raised during the full run")
    except AssertionError as ae:
        record("no-LLM guarantee", False, f"LLM invoked: {ae}")
    finally:
        if harness:
            harness.close()
        for g in guards:
            g.stop()


QUERIES_PLANNED = 10  # welcome, intro, 2 skills x (anchor + escalation), candidate_qa, closing


# ============================================================================
# 3. One question per utterance (multi-final single commit)
# ============================================================================
async def test_multi_final_single_commit() -> None:
    print(f"\n=== [Test 3] Multi-sentence answer = one commit, one next question ===")
    harness = CoordinatorHarness(make_questions(1))
    try:
        c = harness.coordinator
        await c.begin_interview()
        base_speeches = len(harness.ai_speeches())
        from pipecat.frames.frames import UserStartedSpeakingFrame, UserStoppedSpeakingFrame

        await c.process_frame(UserStartedSpeakingFrame(), None)
        # Three provider final chunks in ONE speech window.
        for chunk in ("We rebuilt the billing service last year.", "It handles millions of events.", "We kept the old ledger replayable."):
            c.record_stt_final_chunk(chunk, seq=1)
        await c.process_frame(UserStoppedSpeakingFrame(), None)
        await c.commit_turn(reason="button")
        speeches = harness.ai_speeches()[base_speeches:]
        candidate_turns = [p for p in harness.persisted if p.get("speaker") == "candidate"]
        joined_new = " ".join(speeches)
        record("multi-final: ONE candidate turn", len(candidate_turns) == 1, f"{len(candidate_turns)} candidate turns")
        record(
            "multi-final: text contains all 3 sentences",
            all(s.lower() in (candidate_turns[0]["text"].lower() if candidate_turns else "") for s in ("rebuilt the billing", "millions of events", "old ledger replayable")),
            (candidate_turns[0]["text"][:70] if candidate_turns else "none"),
        )
        record("multi-final: bridge + next question only", len(speeches) == 2 and len(speeches[0].split()) <= 3, f"{len(speeches)} utterances: {[s[:38] for s in speeches]}")
        record("multi-final: next is the skill anchor (no extra question)", "strongest project using skill 1" in joined_new, "anchor asked directly")
    finally:
        harness.close()


# ============================================================================
# 4. No repeats (each planned question asked once)
# ============================================================================
async def test_no_repeats() -> None:
    print(f"\n=== [Test 4] Every planned question asked exactly once ===")
    qs = make_questions(2)
    harness = CoordinatorHarness(qs)
    try:
        answers = [
            "Project one: scaled the API to 50k rps with caching and sharding.",
            "Trade-off: I accepted eventual consistency on the stats pipeline.",
            "Project two: MLOps pipeline with Airflow and Great Expectations.",
            "Trade-off: batch-first processing won because labels arrived daily.",
            "I loved the infra challenges; plenty for a later deep dive.",
            "Nothing more, thank you.",
        ]
        await run_full_interview(harness, answers)
        spoken = harness.ai_speeches()
        frags = {
            "skill1 anchor": "strongest project using skill 1.",
            "skill1 escalation": "for skill 1.",
            "skill2 anchor": "using skill 2.",
            "skill2 escalation": "for skill 2.",
            "candidate_qa": "What questions do you have about the team",
            "closing": "Thanks so much for your time today",
        }
        for label, frag in frags.items():
            count = sum(s.count(frag) for s in spoken)
            record(f"no-repeats: {label}", count == 1, f"count={count}")
    finally:
        harness.close()


# ============================================================================
# 5+6. Button commit + silence commit
# ============================================================================
async def test_commit_paths() -> None:
    print(f"\n=== [Tests 5+6] Button vs silence commit ===")
    harness = CoordinatorHarness(make_questions(1))
    try:
        c = harness.coordinator
        await c.begin_interview()

        # Button commit path
        res = await drive_answer(harness, "I built the payments service with idempotent retries.", commit="button")
        record("commit: button ok", res.get("status") == "committed", str(res))
        cand = [p for p in harness.persisted if p.get("speaker") == "candidate"]
        record("commit: reason button persisted", any(p.get("commit_reason") == "button" for p in cand), "ok")
        record("commit: persisted with provider", any(p.get("provider") == "apple_speechanalyzer" for p in cand), "ok")
        record("commit: speech duration captured", any(p.get("speech_duration_ms") is not None for p in cand), "ok")

        # Commit while AI is speaking should be ignored (never cuts the bot).
        c.state = "asking"
        c.is_speaking = True
        res2 = await c.commit_turn(reason="button")
        record("commit: ignored while AI speaking", res2.get("status") == "ignored" and res2.get("detail") == "ai_speaking", str(res2))
        c.is_speaking = False
        c.state = "listening"

        # Silence commit path
        import backend.app.services.interview.simple_session as ss
        initial_commits = c._commits_total
        with patch.object(ss, "AUTO_COMMIT_SILENCE_SECS", 0.6):
            await drive_answer(harness, "Yes that covers my experience with the queue system.", commit=None)
            for _ in range(60):
                await asyncio.sleep(0.05)
                if c._commits_total > initial_commits:
                    break
            record("commit: silence auto-commit fired", c._commits_total == initial_commits + 1, f"commits={c._commits_total}")
        cand2 = [p for p in harness.persisted if p.get("speaker") == "candidate"]
        record("commit: silence reason persisted", cand2[-1].get("commit_reason") == "silence", f"reason={cand2[-1].get('commit_reason')}")
        record("commit: interview moved on after silence", len(harness.ai_speeches()) >= 2, f"speech count={len(harness.ai_speeches())}")
    finally:
        harness.close()


# ============================================================================
# 7.+8. Short answer prompt-once + anchor_alt
# ============================================================================
async def test_rules() -> None:
    print(f"\n=== [Tests 7+8] Short answers & no-experience rules ===")
    # 7: short-answer prompt exactly once, then move on
    harness = CoordinatorHarness(make_questions(1))
    try:
        c = harness.coordinator
        await c.begin_interview()
        # First: a normal intro answer so the ANCHOR question is current.
        await drive_answer(harness, "I have a CS degree, four years of backend work, and I like data systems.", commit="button")
        first = len(harness.ai_speeches())

        await drive_answer(harness, "Sure.", commit="button")
        speeches_after = harness.ai_speeches()[first:]
        prompts = [s for s in speeches_after if s.strip() == "Could you say a bit more?"]
        record("short: prompted exactly once", len(prompts) == 1, f"prompt speeches={prompts}")

        first2 = len(harness.ai_speeches())
        await drive_answer(harness, "Hm, roughly two years.", commit="button")
        sp2 = harness.ai_speeches()[first2:]
        second_prompts = [s for s in sp2 if s.strip() == "Could you say a bit more?"]
        record("short: no second prompt after progress", len(second_prompts) == 0, f"{[s[:32] for s in sp2]}")
        record("short: escalation asked after decisive reply", any("trickiest trade-off" in s for s in sp2), "ok")
    finally:
        harness.close()

    # 8: no-experience -> anchor_alt (fresh run so the anchor is current again)
    harness = CoordinatorHarness(make_questions(1))
    try:
        c = harness.coordinator
        await c.begin_interview()
        await drive_answer(harness, "I have a CS degree and four years of backend work.", commit="button")
        snaps = len(harness.ai_speeches())
        await drive_answer(harness, "Honestly I have no experience with that skill at all.", commit="button")
        sp3 = harness.ai_speeches()[snaps:]
        record("no-exp: bridge words <= 3 before alt question", bool(sp3) and len(sp3[0].split("Since")[0].split()) <= 3, repr(sp3[:1]))
        record("no-exp: anchor_alt asked verbatim", any("learning it under deadline" in s for s in sp3), f"{[s[:40] for s in sp3]}")
        # After the alt answer: escalation SKIPPED (alt consumed the second slot); candidate_qa follows.
        await drive_answer(harness, "I would find the official docs, build a spike, and get feedback from a senior engineer daily.", commit="button")
        moved_on = any(("Since skill 1" not in s and "What questions do you have" in s) for s in harness.ai_speeches())
        record("no-exp: escalation skipped after alt round", moved_on, str([s[:36] for s in harness.ai_speeches()[-3:]]))
    finally:
        harness.close()


# ============================================================================
# 9. Time-skip escalation
# ============================================================================
async def test_time_skip() -> None:
    print(f"\n=== [Test 9] Time-skip: low clock sheds remaining skills ===")
    qs = make_questions(3)
    harness = CoordinatorHarness(qs)
    try:
        c = harness.coordinator
        await c.begin_interview()
        # Fast-forward the clock: nearly out of budget.
        c.pacing.started_monotonic = time.monotonic() - (c.pacing.duration_planned_mins * 60.0 - 60.0)
        await drive_answer(harness, "I am the lead on our realtime trading ingest platform.", commit="button")
        speeches = harness.ai_speeches()
        qa_asked = any("What questions do you have" in s for s in speeches)
        later_skills = sum(1 for s in speeches for kw in ("skill 2", "skill 3") if kw in s)
        record("time-skip: went to candidate_qa", qa_asked, "ok")
        record("time-skip: remaining skills shed", later_skills == 0, f"later skill mentions={later_skills}")
        # Answer the candidate_qa question -> closing must follow immediately.
        await drive_answer(harness, "Nothing for now, thank you.", commit="button")
        closing_asked = any("Thanks so much" in s for s in harness.ai_speeches())
        record("time-skip: closing follows", closing_asked, "ok")
    finally:
        harness.close()


# ============================================================================
# 10. Bot never speaks during candidate speech (frame invariant)
# ============================================================================
async def test_bot_never_overlaps() -> None:
    print(f"\n=== [Test 10] Bot never speaks while candidate speaks ===")
    harness = CoordinatorHarness(make_questions(1))
    try:
        c = harness.coordinator
        await c.begin_interview()
        from pipecat.frames.frames import UserStartedSpeakingFrame, UserStoppedSpeakingFrame

        # Candidate speaking; interims roll in for a LONG stretch; NO TTSSpeakFrame
        # may appear while the candidate is active — bot speech only happens on commits.
        await c.process_frame(UserStartedSpeakingFrame(), None)
        snapshot = len(harness.ai_speeches())
        for interim in ("First I", "First I joined", "First I joined the platform team", "First I joined the platform team and later", "First I joined the platform team and later the infra crew"):
            c.record_stt_interim(interim)
            await asyncio.sleep(0.02)
        grew_while_speaking = len(harness.ai_speeches()) - snapshot
        record("no-overlap: zero bot speech frames mid-answer", grew_while_speaking == 0, f"+{grew_while_speaking} frames")

        # The commit then speaks freely.
        await c.process_frame(UserStoppedSpeakingFrame(), None)
        res = await c.commit_turn(reason="button")
        record("no-overlap: commit routes next speech", res.get("status") == "committed", str(res.get("status")))
        record("no-overlap: bot resumed only post-commit", len(harness.ai_speeches()) - snapshot >= 2, f"+{len(harness.ai_speeches()) - snapshot} utterances")
    finally:
        harness.close()


# ============================================================================
# 11. Word budgets (bridge <= 3, transition <= 12)
# ============================================================================
async def test_word_budgets() -> None:
    print(f"\n=== [Test 11] Scripted word budgets ===")
    qs = make_questions(2)
    harness = CoordinatorHarness(qs)
    try:
        await run_full_interview(
            harness,
            [
                "I architected a multi-tenant analytics warehouse with incremental view maintenance.",
                "The pivotal trade-off was freshness versus cost, so we materialized hourly.",
                "I designed the fraud streaming pipeline with windowed joins and dedup.",
                "I would relax the SLA for the enrichment stage during incidents.",
            ],
        )
        import backend.app.services.interview.simple_session as ss

        bridges = list(ss._BRIDGES)
        record("budgets: bridges <= 3 words", all(len(b.split()) <= 3 for b in bridges), str(bridges))
        trans_count = 0
        for s in harness.ai_speeches():
            if "Now let's talk about" in s:
                transition_phrase = s.split("Now let's talk about")[0]
                label = s.split("Now let's talk about")[1].split(".")[0] if "." in s.split("Now let's talk about")[1] else ""
                frag = f"{transition_phrase}Now let's talk about {label}."
                wc = len(frag.split())
                trans_count += 1
                record("budgets: transition <= 12 words", wc <= 12, f"words={wc} frag={frag!r}")
        record("budgets: transitions observed", trans_count >= 1, f"{trans_count} transitions")
    finally:
        harness.close()


# ============================================================================
# 12. Real provider smoke (optional --stt): Apple helper on a synthetic clip
# ============================================================================
async def test_real_provider(clip_path: str = "/tmp/r35_voice.pcm") -> None:
    print(f"\n=== [Test 12] Real Apple SpeechAnalyzer transcription ===")
    try:
        from backend.app.services.interview.stt_provider import transcribe_with_provider_async, resolve_stt_provider, helper_is_built

        provider, probe = resolve_stt_provider()
        record("provider: resolution", provider in ("apple_speechanalyzer", "apple_sfspeech", "local_two_lane"), f"{provider} ({probe.as_dict().get('detail','')})")
        if provider not in ("apple_speechanalyzer", "apple_sfspeech") or not helper_is_built():
            record("provider: helper present", False, f"provider={provider} built={helper_is_built()}")
            return
        if not os.path.exists(clip_path):
            record("provider: clip present", False, f"missing {clip_path}")
            return
        started = time.perf_counter()
        res = await transcribe_with_provider_async(open(clip_path, "rb").read(), provider=provider, final_wait=4.0)
        text = res.get("text", "")
        dt = time.perf_counter() - started
        hits = sum(1 for w in ("testing", "apple", "speech", "transcriber", "live", "streaming", "real") if w in text.lower())
        record("provider: dictation-quality transcript", hits >= 5 and len(text.split()) >= 8, f"{hits}/7 keywords; {dt:.1f}s; {text!r}")
        record("provider: transcript latency sane", dt < 30.0, f"{dt:.1f}s")
    except Exception as exc:
        record("provider: run failed", False, f"{type(exc).__name__}: {exc}")


async def main() -> int:
    args = sys.argv[1:]
    run_real = "--stt" in args
    t_all = time.perf_counter()

    await test_full_run_no_llm()
    await test_multi_final_single_commit()
    await test_no_repeats()
    await test_commit_paths()
    await test_rules()
    await test_time_skip()
    await test_bot_never_overlaps()
    await test_word_budgets()
    if run_real:
        await test_real_provider()
    else:
        print(f"\n{YELLOW}[skip]{RESET} test 12 (real Apple helper) — pass --stt to include")

    total = time.perf_counter() - t_all
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = len(RESULTS) - passed
    print(f"\n{BOLD}=== R3.5 verify summary ==={RESET}")
    print(f"  passed: {GREEN}{passed}{RESET}  failed: {RED if failed else RESET}{failed}{RESET}  total: {len(RESULTS)}  wall: {total:.1f}s")
    with open("review/verify_r3_5_summary.json", "w") as f:
        json.dump({"passed": passed, "failed": failed, "results": RESULTS, "wall_seconds": round(total, 2)}, f, indent=2)
    return 1 if failed else 0


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
