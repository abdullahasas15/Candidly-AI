"""Comprehensive Unit Tests for Interview Conductor (v2).

Tests the pure reducer step(state, event) -> (new_state, effects)
with a fake clock, zero network, and 100% deterministic execution.
"""

import json
from typing import Any, Dict, List, Tuple
import pytest

from backend.app.services.interview_v2.conductor import (
    ConductorEffect,
    ConductorEvent,
    ConductorPhase,
    ConductorState,
    DecisionReady,
    AckReady,
    PlanQuestion,
    RequestDecision,
    SessionStart,
    TurnStart,
    EagerTurnEnd,
    TurnResumed,
    TurnEnd,
    BotAudioStarted,
    BotSpeechDone,
    Tick,
    ReadyButton,
    CommitButton,
    RepeatRequest,
    EndButton,
    Speak,
    SpeakAck,
    CancelSpeech,
    StartSpeculativeReply,
    CancelSpeculativeReply,
    PlayBridge,
    ScheduleTimer,
    CancelTimer,
    Persist,
    EmitUI,
    step,
)


def complete_intro_and_advance(
    state: ConductorState,
    now_ms: int = 4000,
    intro_ans: str = "I have five years of backend engineering experience with Python.",
) -> ConductorState:
    state, _ = step(state, TurnEnd(text=intro_ans, turn_id="t_intro", now_ms=now_ms))
    state, effects = step(state, Tick(now_ms=now_ms + 300))
    req = next((e for e in effects if isinstance(e, RequestDecision)), None)
    if req:
        anchor_q = state.skill_questions.get("Python", {}).get("anchor")
        state, _ = step(
            state,
            DecisionReady(
                token=req.token,
                decision={
                    "action": "new_topic",
                    "ack": "Thanks for sharing.",
                    "target_skill": "Python",
                    "question": anchor_q.question_text if anchor_q else "",
                },
                now_ms=now_ms + 400,
            ),
        )
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=now_ms + 1000))
    return state


def make_test_plan() -> Dict[str, Any]:
    """Create a realistic materializer-style interview plan with 3 skills."""
    return {
        "questions": [
            {
                "question_index": 0,
                "kind": "welcome",
                "skill_name": "Welcome & Agenda",
                "question_text": "Hi there! Welcome to your interview. Today we will cover Python, Distributed Systems, and Database Design. Ready?",
                "priority_tier": "P0",
            },
            {
                "question_index": 1,
                "kind": "intro_hook",
                "skill_name": "Introduction",
                "question_text": "To start off, could you introduce yourself and tell us about your recent work?",
                "priority_tier": "P0",
            },
            # Skill 1: Python
            {
                "question_index": 2,
                "kind": "anchor",
                "skill_name": "Python",
                "question_text": "How do you handle concurrency in Python using asyncio versus multiprocessing?",
                "priority_tier": "P0",
            },
            {
                "question_index": 3,
                "kind": "anchor_alt",
                "skill_name": "Python",
                "question_text": "Can you explain how the GIL affects CPU-bound versus I/O-bound tasks in Python?",
                "priority_tier": "P0",
            },
            {
                "question_index": 4,
                "kind": "escalation",
                "skill_name": "Python",
                "question_text": "What specific profiling tools have you used to find CPU bottlenecks in a Python service?",
                "priority_tier": "P0",
            },
            {
                "question_index": 20,
                "kind": "probe",
                "skill_name": "Python",
                "probe_id": "probe_celery",
                "question_text": "How do you configure Celery worker concurrency with asyncio or threads?",
                "trigger_condition": "mentions task queues or celery or background workers",
                "priority_tier": "P1",
            },
            # Skill 2: Distributed Systems
            {
                "question_index": 5,
                "kind": "anchor",
                "skill_name": "Distributed Systems",
                "question_text": "How do you design a reliable retry mechanism using exponential backoff and jitter?",
                "priority_tier": "P0",
            },
            {
                "question_index": 6,
                "kind": "anchor_alt",
                "skill_name": "Distributed Systems",
                "question_text": "What strategies do you use to prevent cascading failures across microservices?",
                "priority_tier": "P0",
            },
            {
                "question_index": 7,
                "kind": "escalation",
                "skill_name": "Distributed Systems",
                "question_text": "How would you handle a split-brain scenario in a distributed consensus cluster?",
                "priority_tier": "P0",
            },
            # Skill 3: Database Design
            {
                "question_index": 8,
                "kind": "anchor",
                "skill_name": "Database Design",
                "question_text": "How do you decide when to use a composite index in PostgreSQL?",
                "priority_tier": "P0",
            },
            {
                "question_index": 9,
                "kind": "anchor_alt",
                "skill_name": "Database Design",
                "question_text": "How do you execute schema migrations without taking downtime?",
                "priority_tier": "P0",
            },
            {
                "question_index": 10,
                "kind": "escalation",
                "skill_name": "Database Design",
                "question_text": "What partitioning strategy would you choose for a multi-terabyte timeseries table?",
                "priority_tier": "P0",
            },
            # Wrap-up
            {
                "question_index": 11,
                "kind": "candidate_qa",
                "skill_name": "Candidate Q&A",
                "question_text": "Now the floor is yours. What questions do you have for us?",
                "priority_tier": "P0",
            },
            {
                "question_index": 12,
                "kind": "closing",
                "skill_name": "Closing",
                "question_text": "Thank you for speaking with us today. Have a great day!",
                "priority_tier": "P0",
            },
        ]
    }


def start_session(plan: Dict[str, Any] = None) -> Tuple[ConductorState, List[ConductorEffect]]:
    """Helper to start session and return initialized state."""
    state = ConductorState()
    p = plan or make_test_plan()
    return step(state, SessionStart(session_id="test_sess_01", plan=p, now_ms=1000))


# -----------------------------------------------------------------------------
# Test 1: Duplicate TurnEnd
# -----------------------------------------------------------------------------
def test_duplicate_turn_end():
    state, effects = start_session()
    # Finish welcome speech
    speech_id = state.active_speech_id
    state, _ = step(state, BotSpeechDone(speech_id=speech_id, now_ms=2000))
    # Pass ready gate
    state, _ = step(state, ReadyButton(now_ms=2100))
    intro_speech = state.active_speech_id
    state, _ = step(state, BotSpeechDone(speech_id=intro_speech, now_ms=3000))

    # Candidate speaks first turn
    text = "I have been building distributed backends for five years."
    state, effects1 = step(state, TurnEnd(text=text, turn_id="t1", now_ms=3500))
    assert state.answer_buffer == text

    # Send duplicate TurnEnd with the same turn_id
    state, effects2 = step(state, TurnEnd(text=text, turn_id="t1", now_ms=3550))
    assert state.answer_buffer == text
    assert len(effects2) == 0  # Duplicate ignored completely


# -----------------------------------------------------------------------------
# Test 2: Late TurnStart After Commit (Un-commit Before BotAudioStarted)
# -----------------------------------------------------------------------------
def test_late_turn_start_uncommit():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Candidate speaks complete answer
    state, _ = step(state, TurnStart(now_ms=3200))
    state, _ = step(state, TurnEnd(text="I primarily use Python asyncio for IO-bound web services.", turn_id="t1", now_ms=4000))

    # Commit fires after 300ms grace at 4300ms
    state, commit_effects = step(state, Tick(now_ms=4300))
    assert state.is_committed is True
    assert any(isinstance(e, Persist) for e in commit_effects)
    assert any(isinstance(e, RequestDecision) for e in commit_effects)
    assert state.bot_audio_started is False

    # Candidate starts speaking again BEFORE BotAudioStarted!
    state, resume_effects = step(state, TurnStart(now_ms=4400))
    assert any(isinstance(e, CancelSpeech) for e in resume_effects)
    assert state.is_committed is False
    assert "I primarily use Python asyncio" in state.answer_buffer

    # Candidate continues answer
    state, _ = step(state, TurnEnd(text="And we use multiprocessing for heavy CPU calculations.", turn_id="t2", now_ms=5000))
    assert "multiprocessing for heavy CPU calculations" in state.answer_buffer

    # Once BotAudioStarted arrives after a final commit, commit is permanent
    state, commit_effects2 = step(state, Tick(now_ms=5300))
    assert state.is_committed is True
    req2 = next(e for e in commit_effects2 if isinstance(e, RequestDecision))
    state, dec_effects2 = step(
        state,
        DecisionReady(
            token=req2.token,
            decision={
                "action": "new_topic",
                "ack": "Thanks.",
                "target_skill": "Python",
                "question": "How do you handle concurrency in Python?",
            },
            now_ms=5350,
        ),
    )
    speech_id = state.active_speech_id
    state, _ = step(state, BotAudioStarted(speech_id=speech_id, now_ms=5400))
    assert state.bot_audio_started is True

    # Late TurnStart now cannot un-commit
    state, after_effects = step(state, TurnStart(now_ms=5500))
    assert not any(isinstance(e, CancelSpeech) for e in after_effects)
    assert state.is_committed is True


# -----------------------------------------------------------------------------
# Test 3: Double Commit Protection
# -----------------------------------------------------------------------------
def test_double_commit_protection():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    state, _ = step(state, TurnEnd(text="I have worked extensively with Python and relational databases.", turn_id="t1", now_ms=3500))

    # First commit via Tick
    state, effects1 = step(state, Tick(now_ms=3800))
    persists1 = [e for e in effects1 if isinstance(e, Persist)]
    assert len(persists1) == 1

    # Immediate second CommitButton trigger
    state, effects2 = step(state, CommitButton(now_ms=3810))
    persists2 = [e for e in effects2 if isinstance(e, Persist)]
    assert len(persists2) == 0  # No double persist or double commit


# -----------------------------------------------------------------------------
# Test 4: Stale Timers
# -----------------------------------------------------------------------------
def test_stale_timers():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Incomplete text schedules timer for +2500ms (5500ms)
    state, effects = step(state, TurnEnd(text="Well, because", turn_id="t1", now_ms=3000))
    assert "commit" in state.active_timers
    old_commit_at = state.active_timers["commit"]["at_ms"]

    # Candidate speaks again at 4000ms, cancelling old commit timer
    state, _ = step(state, TurnStart(now_ms=4000))
    assert "commit" not in state.active_timers

    # Tick at 5500ms (when old timer would have fired)
    state, tick_effects = step(state, Tick(now_ms=old_commit_at))
    assert state.is_committed is False
    assert not any(isinstance(e, Persist) for e in tick_effects)


# -----------------------------------------------------------------------------
# Test 5: Split Answer (Two TurnEnds Merge into One)
# -----------------------------------------------------------------------------
def test_split_answer_merge():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # TurnEnd 1: with comma
    state, _ = step(state, TurnEnd(text="We used PostgreSQL with connection pooling,", turn_id="t1", now_ms=3200))
    # TurnStart 2: 2s later
    state, _ = step(state, TurnStart(now_ms=5200))
    # TurnEnd 2: 3s after first
    state, _ = step(state, TurnEnd(text="and configured read replicas for high throughput.", turn_id="t2", now_ms=6200))

    expected = "We used PostgreSQL with connection pooling, and configured read replicas for high throughput."
    assert state.answer_buffer == expected

    # Commits cleanly after complete grace
    state, commit_effects = step(state, Tick(now_ms=6500))
    assert state.is_committed is True
    persist = next(e for e in commit_effects if isinstance(e, Persist))
    assert persist.turn["answer"] == expected


# -----------------------------------------------------------------------------
# Test 6: Incomplete Ending ("...because" Extends Wait to 2500ms, Then Resumes)
# -----------------------------------------------------------------------------
def test_incomplete_ending_extends_wait():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Candidate says "...because"
    state, effects = step(state, TurnEnd(text="We opted for Redis over Memcached because", turn_id="t1", now_ms=3100))
    timer_effect = next(e for e in effects if isinstance(e, ScheduleTimer) and e.name == "commit")
    assert timer_effect.at_ms == 3100 + 2500  # Incomplete grace = 2500ms

    # Candidate resumes at 4500ms
    state, resume_effects = step(state, TurnStart(now_ms=4500))
    assert any(isinstance(e, CancelTimer) and e.name == "commit" for e in resume_effects)


# -----------------------------------------------------------------------------
# Test 7: COMPLETE Ending Commits at ~300ms
# -----------------------------------------------------------------------------
def test_complete_ending_commits_fast():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Complete sentence: >=6 words, ends with '.', no filler at end
    text = "We configured exponential backoff with full jitter to avoid thundering herds."
    state, effects = step(state, TurnEnd(text=text, turn_id="t1", now_ms=3500))
    timer_effect = next(e for e in effects if isinstance(e, ScheduleTimer) and e.name == "commit")
    assert timer_effect.at_ms == 3500 + 300  # 300ms fast commit grace

    # At 3800ms commit executes
    state, commit_effects = step(state, Tick(now_ms=3800))
    assert state.is_committed is True


# -----------------------------------------------------------------------------
# Test 8: Eager Then Resumed Cancels Speculation
# -----------------------------------------------------------------------------
def test_eager_then_resumed_cancels_speculation():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Candidate starts speaking
    state, _ = step(state, TurnStart(now_ms=3200))
    # EagerTurnEnd fires
    state, eager_effects = step(state, EagerTurnEnd(text="I think we should", now_ms=3500))
    spec_start = next(e for e in eager_effects if isinstance(e, StartSpeculativeReply))
    assert spec_start.token == state.active_speculation_token

    # Candidate resumes speaking
    state, resumed_effects = step(state, TurnResumed(now_ms=3600))
    cancel_spec = next(e for e in resumed_effects if isinstance(e, CancelSpeculativeReply))
    assert cancel_spec.token == spec_start.token
    assert state.active_speculation_token is None


# -----------------------------------------------------------------------------
# Test 9: Bridge Fires Only Once After 700ms
# -----------------------------------------------------------------------------
def test_bridge_fires_once_and_rotates():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Complete answer
    state, _ = step(state, TurnEnd(text="I implemented composite indexes on tenant ID and timestamp.", turn_id="t1", now_ms=3200))
    # Commit fires at 3500ms
    state, commit_effects = step(state, Tick(now_ms=3500))
    assert any(isinstance(e, ScheduleTimer) and e.name == "bridge" and e.at_ms == 4200 for e in commit_effects)

    # 700ms elapsed at 4200ms -> Bridge fires
    state, bridge_effects1 = step(state, Tick(now_ms=4200))
    bridge1 = next(e for e in bridge_effects1 if isinstance(e, PlayBridge))
    assert bridge1.text in ["Mm-hm.", "Right.", "Okay."]

    # Another tick at 4300ms -> Bridge does NOT fire again
    state, bridge_effects2 = step(state, Tick(now_ms=4300))
    assert not any(isinstance(e, PlayBridge) for e in bridge_effects2)

    # Deliver decision for intro so next question is asked
    req1 = next(e for e in commit_effects if isinstance(e, RequestDecision))
    anchor_q = state.skill_questions.get("Python", {}).get("anchor")
    state, _ = step(
        state,
        DecisionReady(
            token=req1.token,
            decision={
                "action": "new_topic",
                "ack": "Understood.",
                "target_skill": "Python",
                "question": anchor_q.question_text if anchor_q else "",
            },
            now_ms=4350,
        ),
    )

    # Finish bot speech and answer next question to test bridge rotation
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=5000))
    state, _ = step(state, TurnEnd(text="We also tuned our database connection pool settings.", turn_id="t2", now_ms=5500))
    state, _ = step(state, Tick(now_ms=5800))
    state, bridge_effects3 = step(state, Tick(now_ms=6500))
    bridge2 = next(e for e in bridge_effects3 if isinstance(e, PlayBridge))
    assert bridge2.text != bridge1.text  # Rotated, never repeated twice in a row


def test_reply_ready_in_300ms_cancels_bridge_timer():
    """Verify that if reply audio starts in 300ms, bridge timer is cancelled and no bridge plays."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Candidate answers
    state, _ = step(state, TurnEnd(text="I implemented composite indexes on tenant ID and timestamp.", turn_id="t1", now_ms=3200))
    # Commit fires at 3500ms -> schedules bridge for 4200ms (700ms after commit)
    state, commit_effects = step(state, Tick(now_ms=3500))
    assert any(isinstance(e, ScheduleTimer) and e.name == "bridge" and e.at_ms == 4200 for e in commit_effects)
    assert "bridge" in state.active_timers

    # Reply is ready in 300ms (at 3800ms) -> DecisionReady and BotAudioStarted arrive
    req = next(e for e in commit_effects if isinstance(e, RequestDecision))
    anchor_q = state.skill_questions.get("Python", {}).get("anchor")
    state, dec_effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "action": "new_topic",
                "ack": "Understood.",
                "target_skill": "Python",
                "question": anchor_q.question_text if anchor_q else "",
            },
            now_ms=3800,
        ),
    )
    speak = next(e for e in dec_effects if isinstance(e, Speak))
    state, audio_effects = step(state, BotAudioStarted(speech_id=speak.speech_id, now_ms=3800))
    # Must cancel the bridge timer immediately
    assert any(isinstance(e, CancelTimer) and e.name == "bridge" for e in audio_effects)
    assert "bridge" not in state.active_timers
    assert state.bot_audio_started is True

    # At 4200ms (when bridge would have fired): Tick occurs
    state, tick_effects = step(state, Tick(now_ms=4200))
    # No bridge must fire!
    assert not any(isinstance(e, PlayBridge) for e in tick_effects)
    assert state.bridge_played_for_commit is False


# -----------------------------------------------------------------------------
# Test 10: Silence Progression (25s Nudge, 60s Repeat, 90s Move On)
# -----------------------------------------------------------------------------
def test_silence_progression():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    # Question becomes active at 3000ms
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    assert state.question_active_at_ms == 3000

    # 1. At 25s elapsed (28000ms): Nudge
    state, nudge_effects = step(state, Tick(now_ms=28000))
    nudge_speak = next(e for e in nudge_effects if isinstance(e, Speak))
    assert "Take your time. Want me to repeat the question?" in nudge_speak.text
    # Bot finishes speaking nudge
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=30000))

    # 2. At 60s elapsed from question start (63000ms): Repeat question
    state, repeat_effects = step(state, Tick(now_ms=63000))
    repeat_speak = next(e for e in repeat_effects if isinstance(e, Speak))
    intro_q = next(q for q in state.questions if q.kind == "intro_hook")
    assert repeat_speak.text == intro_q.question_text
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=65000))

    # 3. At 90s elapsed from question start (93000ms): Mark unanswered and move on!
    state, timeout_effects = step(state, Tick(now_ms=93000))
    persist = next(e for e in timeout_effects if isinstance(e, Persist))
    assert persist.turn["unanswered"] is True
    # Next question asked (Python anchor)
    next_speak = next(e for e in timeout_effects if isinstance(e, Speak))
    assert "How do you handle concurrency in Python" in next_speak.text


# -----------------------------------------------------------------------------
# Test 11: Repeat Request (< 6 Words)
# -----------------------------------------------------------------------------
def test_repeat_request():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Spoken repeat request < 6 words
    state, repeat_effects = step(state, TurnEnd(text="Can you repeat that?", turn_id="t1", now_ms=3500))
    speak_effect = next(e for e in repeat_effects if isinstance(e, Speak))
    intro_q = next(q for q in state.questions if q.kind == "intro_hook")
    assert speak_effect.text == intro_q.question_text
    assert state.is_committed is False


# -----------------------------------------------------------------------------
# Test 12: Short Answers (< 6 Words -> Escalation)
# -----------------------------------------------------------------------------
def test_short_answer_uses_escalation():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Intro answer (>= 6 words)
    state = complete_intro_and_advance(state, now_ms=3500, intro_ans="I am a software engineer with extensive backend experience.")
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # Short answer (< 6 words): "Yes, I used asyncio." (4 words)
    # Classified as INCOMPLETE (< 6 words), so commit grace is 2500ms -> fires at 5000 + 2500 = 7500ms
    state, _ = step(state, TurnEnd(text="Yes, I used asyncio.", turn_id="t2", now_ms=5000))
    state, effects = step(state, Tick(now_ms=7500))

    # In Phase A: commit emits RequestDecision and enters AWAIT_DECISION
    assert state.awaiting_decision is True
    req = next(e for e in effects if isinstance(e, RequestDecision))
    esc_q = next(q for q in state.questions if q.kind == "escalation" and q.skill_name == "Python")

    # Agentic decision selects escalation
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "escalate",
                "followup": esc_q.question_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=7600,
        ),
    )
    speak_effect = next(e for e in effects if isinstance(e, Speak))
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    assert esc_q.question_text in speak_effect.question_text


# -----------------------------------------------------------------------------
# Test 13: Resume from Serialized State Mid-Interview
# -----------------------------------------------------------------------------
def test_state_serialization_roundtrip():
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Candidate starts answering
    state, _ = step(state, TurnStart(now_ms=3200))
    state, _ = step(state, TurnEnd(text="I have worked with distributed databases and caching.", turn_id="t1", now_ms=3500))

    # Serialize to JSON and deserialize back
    state_dict = state.to_dict()
    json_str = json.dumps(state_dict)
    loaded_dict = json.loads(json_str)
    resumed_state = ConductorState.from_dict(loaded_dict)

    # Continue from resumed state
    assert resumed_state.session_id == state.session_id
    assert resumed_state.phase == state.phase
    assert resumed_state.answer_buffer == state.answer_buffer
    assert "commit" in resumed_state.active_timers

    # Tick to commit on resumed state
    resumed_state, commit_effects = step(resumed_state, Tick(now_ms=3800))
    assert resumed_state.is_committed is True
    assert any(isinstance(e, Persist) for e in commit_effects)


# -----------------------------------------------------------------------------
# Test 14: Never Skips a Skill, Never Repeats an Anchor, Never Hangs
# -----------------------------------------------------------------------------
def test_full_interview_progression_complete():
    """Verify an end-to-end hands-free interview with all skills probed."""
    state, effects = start_session()
    assert state.phase in (ConductorPhase.GREETING, ConductorPhase.WELCOME)

    asked_anchors: List[str] = []

    # 1. Greeting -> Greeting Response
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    assert state.phase == ConductorPhase.GREETING_RESPONSE

    # 2. Greeting answered -> Agenda
    state, _ = step(state, TurnEnd(text="I am doing well, thank you.", turn_id="greeting_1", now_ms=2500))
    assert state.phase == ConductorPhase.AGENDA
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    assert state.phase == ConductorPhase.AGENDA_RESPONSE

    # 3. Agenda confirmed -> Intro
    state, _ = step(state, TurnEnd(text="Sounds good, let's start.", turn_id="agenda_1", now_ms=3200))
    assert state.phase == ConductorPhase.INTRO
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3500))

    # 4. Intro Answer -> Python Anchor
    state = complete_intro_and_advance(state, now_ms=4000)
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    asked_anchors.append(state.questions[state.current_question_index].question_text)

    # 4. Python Anchor Answer -> Python Follow-up
    state, _ = step(state, TurnEnd(text="We use asyncio for network coroutines and multiprocessing for CPU tasks.", turn_id="t_py_1", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    assert state.awaiting_decision is True
    req = next(e for e in effects if isinstance(e, RequestDecision))
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "probe",
                "followup": "Can you elaborate on task cancellation in asyncio?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=6500))

    # 5. Python Follow-up Answer -> Distributed Systems Anchor
    state, _ = step(state, TurnEnd(text="The GIL prevents true multi-core Python threading on CPU tasks.", turn_id="t_py_2", now_ms=7000))
    state, effects = step(state, Tick(now_ms=7300))
    assert state.awaiting_decision is True
    req = next(e for e in effects if isinstance(e, RequestDecision))
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Clear point.",
                "action": "next",
                "followup": "",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=7400,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    dist_anchor = state.questions[state.current_question_index].question_text
    assert dist_anchor not in asked_anchors
    asked_anchors.append(dist_anchor)
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=8000))

    # 6. Distributed Systems Anchor Answer (Short -> Escalation)
    state, _ = step(state, TurnEnd(text="We use exponential backoff.", turn_id="t_dist_1", now_ms=8500))
    state, effects = step(state, Tick(now_ms=11000))
    assert state.awaiting_decision is True
    req = next(e for e in effects if isinstance(e, RequestDecision))
    esc_dist = next(q for q in state.questions if q.kind == "escalation" and q.skill_name == "Distributed Systems")
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "escalate",
                "followup": esc_dist.question_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=11100,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=12000))

    # 7. Distributed Systems Escalation Answer -> Database Design Anchor
    state, _ = step(state, TurnEnd(text="In split-brain scenarios we require a quorum of nodes.", turn_id="t_dist_2", now_ms=12500))
    state, effects = step(state, Tick(now_ms=12800))
    assert state.awaiting_decision is True
    req = next(e for e in effects if isinstance(e, RequestDecision))
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Makes sense.",
                "action": "next",
                "followup": "",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=12900,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    db_anchor = state.questions[state.current_question_index].question_text
    assert db_anchor not in asked_anchors
    asked_anchors.append(db_anchor)
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=13500))

    # 8. Database Design Anchor Answer -> Database Design Follow-up
    state, _ = step(state, TurnEnd(text="Composite indexes are useful for queries with multiple equality filters.", turn_id="t_db_1", now_ms=14000))
    state, effects = step(state, Tick(now_ms=14300))
    assert state.awaiting_decision is True
    req = next(e for e in effects if isinstance(e, RequestDecision))
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "probe",
                "followup": "How do you choose column ordering in composite indexes?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=14400,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=15000))

    # 9. Database Design Follow-up Answer -> Candidate Q&A
    state, _ = step(state, TurnEnd(text="We run migrations online using expand and contract patterns.", turn_id="t_db_2", now_ms=15500))
    state, effects = step(state, Tick(now_ms=15800))
    assert state.awaiting_decision is True
    req = next(e for e in effects if isinstance(e, RequestDecision))
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Clear point.",
                "action": "next",
                "followup": "",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=15900,
        ),
    )
    assert state.phase == ConductorPhase.CANDIDATE_QA
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=16500))

    # 10. Candidate Q&A Answer -> Closing
    state, _ = step(state, TurnEnd(text="What does a typical on-call rotation look like for this team?", turn_id="t_qa", now_ms=17000))
    state, _ = step(state, Tick(now_ms=17300))
    assert state.phase == ConductorPhase.CLOSING
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=18000))

    # Final state: COMPLETED
    assert state.phase == ConductorPhase.COMPLETED

    # Assert all 3 skills were probed
    assert len(asked_anchors) == 3
    assert len(set(asked_anchors)) == 3  # No anchor repeated


# -----------------------------------------------------------------------------
# Test 15: Ready Gate Natural Affirmations & Commit Button
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("phrase", [
    "let's begin",
    "lets begin",
    "yes",
    "yeah",
    "ready",
    "sure",
    "i am ready",
    "we can begin",
    "yes please",
    "sounds good",
])
def test_ready_gate_natural_phrases(phrase: str):
    """Candidate saying 'let's begin', 'yes', 'ready', etc. in opening agenda response advances to INTRO."""
    state, _ = start_session()
    # Greeting finishes speaking
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    assert state.phase == ConductorPhase.GREETING_RESPONSE

    # Greeting reply -> Agenda
    state, _ = step(state, TurnEnd(text="I am doing well.", turn_id="greeting_resp", now_ms=2200))
    assert state.phase == ConductorPhase.AGENDA
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2400))
    assert state.phase == ConductorPhase.AGENDA_RESPONSE

    # Candidate speaks affirmative phrase to agenda
    state, effects = step(state, TurnEnd(text=phrase, turn_id="turn_ready", now_ms=2500))
    assert state.phase == ConductorPhase.INTRO
    assert any(isinstance(e, Speak) and "introduce yourself" in e.text.lower() for e in effects)


def test_ready_gate_commit_button():
    """Pressing CommitButton in opening advances directly to INTRO."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    assert state.phase == ConductorPhase.GREETING_RESPONSE

    state, effects = step(state, CommitButton(now_ms=2500))
    assert state.phase == ConductorPhase.INTRO
    assert any(isinstance(e, Speak) for e in effects)


def test_commit_button_with_empty_buffer():
    """Pressing CommitButton with empty answer buffer skips turn cleanly without freezing."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    # In INTRO
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    assert state.phase == ConductorPhase.INTRO

    # Candidate clicks CommitButton without speaking
    state, effects = step(state, CommitButton(now_ms=3500))
    assert state.is_committed is True
    assert "[Skipped by candidate]" in state.committed_answer
    assert any(isinstance(e, Persist) for e in effects)


# =============================================================================
# Phase A Agentic Interview Tests (Requirements 1-11)
# =============================================================================

# -----------------------------------------------------------------------------
# Test 16: Decision Timeout Fallback
# -----------------------------------------------------------------------------
def test_decision_timeout_fallback():
    """If 1500ms elapses without DecisionReady, deterministic fallback picks probe/escalation/next."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # Case A: Candidate mentions keywords matching probe_celery trigger ("task queues or celery or background workers")
    answer_probe = "We use background task queues with Celery workers for async execution."
    state, _ = step(state, TurnEnd(text=answer_probe, turn_id="t_py_probe", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    assert state.awaiting_decision is True
    assert any(isinstance(e, RequestDecision) for e in effects)

    # 1500ms elapses with no DecisionReady -> Tick at 5800 + 1500 = 7300ms
    state, fallback_effects = step(state, Tick(now_ms=7300))
    assert state.awaiting_decision is False
    speak_eff = next(e for e in fallback_effects if isinstance(e, Speak))
    # Fallback matches probe_celery because trigger_condition shared >= 2 content words
    probe_celery = next(q for q in state.questions if getattr(q, "probe_id", None) == "probe_celery")
    assert speak_eff.question_text == probe_celery.question_text
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP


# -----------------------------------------------------------------------------
# Test 17: No Experience Triggers Hypothetical (anchor_alt)
# -----------------------------------------------------------------------------
def test_no_experience_hypothetical():
    """When decision says no_experience=True with action='hypothetical', use anchor_alt."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # Candidate says they have no experience with this topic
    state, _ = step(state, TurnEnd(text="To be honest, I have never worked with Python concurrency directly.", turn_id="t_py_noexp", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    alt_q = next(q for q in state.questions if q.kind == "anchor_alt" and q.skill_name == "Python")
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "No problem.",
                "action": "hypothetical",
                "followup": alt_q.question_text,
                "covered_expectations": [],
                "no_experience": True,
            },
            now_ms=5900,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    assert speak_eff.question_text == alt_q.question_text
    assert speak_eff.ack_text == "No problem."


# -----------------------------------------------------------------------------
# Test 18: Duplicate Follow-up Rejection (>60% token overlap)
# -----------------------------------------------------------------------------
def test_duplicate_followup_rejection():
    """Followup with >60% token overlap with any prior question is rejected; deterministic fallback taken."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # Python anchor text is: "How do you handle concurrency in Python using asyncio versus multiprocessing?"
    state, _ = step(state, TurnEnd(text="We use asyncio for our microservices and multiprocessing for CPU tasks.", turn_id="t_py", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    # Duplicate followup with >60% word overlap with the Python anchor question:
    duplicate_followup = "How do you handle concurrency in Python using asyncio?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "probe",
                "followup": duplicate_followup,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    # Must NOT speak the duplicate question: rejected due to >60% overlap
    assert speak_eff.question_text != duplicate_followup


# -----------------------------------------------------------------------------
# Test 19: Covered Expectations Forces Next
# -----------------------------------------------------------------------------
def test_covered_expectations_forces_next():
    """If all core expectations for the question are covered, action is forced to 'next'."""
    plan = make_test_plan()
    # Add expected_key_points to Python anchor
    for q in plan["questions"]:
        if q["kind"] == "anchor" and q["skill_name"] == "Python":
            q["expected_key_points"] = ["asyncio", "multiprocessing"]

    state, _ = start_session(plan)
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    state, _ = step(state, TurnEnd(text="I use asyncio for I/O and multiprocessing for CPU tasks.", turn_id="t_py", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    # Decision attempts to probe even though all expectations are covered:
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "probe",
                "followup": "Can you tell me more about thread pools?",
                "covered_expectations": ["asyncio", "multiprocessing"],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    # Forced to next skill (Distributed Systems)!
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    dist_anchor = next(q for q in state.questions if q.kind == "anchor" and q.skill_name == "Distributed Systems")
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    assert speak_eff.question_text == f"Let's move on to {dist_anchor.skill_name}. {dist_anchor.question_text}"


# -----------------------------------------------------------------------------
# Test 20: Max 2 Follow-ups Per Skill Forces Next
# -----------------------------------------------------------------------------
def test_max_2_followups_per_skill():
    """At most 2 follow-ups per skill. A 3rd followup attempt is forced to 'next'."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # Artificially set followups_used to 2 for Python
    state.followups_used_per_skill["Python"] = 2

    state, _ = step(state, TurnEnd(text="Here is my answer to the anchor question.", turn_id="t_py", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    # Decision tries to probe again
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "probe",
                "followup": "Can you explain asyncio tasks?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    # Forced to next skill!
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.skill_names[state.current_skill_index] == "Distributed Systems"


# -----------------------------------------------------------------------------
# Test 21: Time Budget (<60s left) Forces Next
# -----------------------------------------------------------------------------
def test_time_budget_forces_next():
    """If time left for the skill is under 60 seconds (< 60,000 ms), followups are forbidden and forced to next."""
    plan = make_test_plan()
    # Python budget = 100,000 ms (100 seconds)
    plan["skill_budgets_ms"] = {"Python": 100000}

    state, _ = start_session(plan)
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # Now time reaches 5000 + 50000 = 55000ms (elapsed 50,000ms out of 100,000ms -> 50,000ms left < 60,000ms)
    state, _ = step(state, TurnEnd(text="We use asyncio tasks extensively in backend services.", turn_id="t_py", now_ms=55000))
    state, effects = step(state, Tick(now_ms=55300))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "probe",
                "followup": "Can you explain task cancellation?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=55400,
        ),
    )
    # Forced to next skill due to < 60s remaining!
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.skill_names[state.current_skill_index] == "Distributed Systems"


# -----------------------------------------------------------------------------
# Test 22: TTS Spoken Text Verbatim Equals Recorded Text
# -----------------------------------------------------------------------------
def test_tts_text_equals_recorded_text():
    """Verify combined spoken text = ack + question, and the question recorded in state exactly equals question_text."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    state, _ = step(state, TurnEnd(text="We use asyncio extensively for task cancellation patterns in our services.", turn_id="t_py", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    followup_q = "Could you explain task cancellation patterns?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "probe",
                "followup": followup_q,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    assert speak_eff.ack_text == "Understood."
    assert speak_eff.question_text == followup_q
    assert speak_eff.text == "Understood. Could you explain task cancellation patterns?"
    # The recorded question in state matches followup_q verbatim
    curr_q = next(q for q in state.questions if q.question_index == state.current_question_index)
    assert curr_q.question_text == followup_q


# -----------------------------------------------------------------------------
# Test 23: Stale Decision Token Ignored
# -----------------------------------------------------------------------------
def test_stale_decision_token_ignored():
    """Stale DecisionReady event with an old/mismatched token is ignored and produces no state corruption."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    state, _ = step(state, TurnEnd(text="We use asyncio for our microservices and multiprocessing for CPU tasks.", turn_id="t_py", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    assert state.awaiting_decision is True

    # Deliver a stale token
    state, effects = step(
        state,
        DecisionReady(
            token="stale_decision_token_12345",
            decision={
                "ack": "Stale ack.",
                "action": "next",
                "followup": "",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    # Must still be awaiting decision for the real token!
    assert state.awaiting_decision is True
    assert not any(isinstance(e, Speak) for e in effects)


# -----------------------------------------------------------------------------
# Test 24: Resume from Serialized State in AWAIT_DECISION
# -----------------------------------------------------------------------------
def test_resume_from_serialized_state_in_await_decision():
    """State serialized while in AWAIT_DECISION can be deserialized and complete successfully on DecisionReady."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    state, _ = step(state, TurnEnd(text="We use asyncio for background task cancellation in our services.", turn_id="t_py", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    assert state.awaiting_decision is True
    token = state.decision_token

    # Serialize to JSON and deserialize
    state_json = json.dumps(state.to_dict())
    resumed_dict = json.loads(state_json)
    resumed_state = ConductorState.from_dict(resumed_dict)

    assert resumed_state.awaiting_decision is True
    assert resumed_state.decision_token == token

    # Deliver DecisionReady to resumed state
    followup_q = "Could you explain background task cancellation in more detail?"
    resumed_state, effects = step(
        resumed_state,
        DecisionReady(
            token=token,
            decision={
                "ack": "Understood.",
                "action": "probe",
                "followup": followup_q,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    assert resumed_state.awaiting_decision is False
    assert resumed_state.phase == ConductorPhase.SKILL_FOLLOWUP
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    assert followup_q in speak_eff.text


# -----------------------------------------------------------------------------
# Test 25: Phase A2 - Clarify Action and Max Once Per Skill
# -----------------------------------------------------------------------------
def test_clarify_action_and_max_once_per_skill():
    """Vague or short answer triggers clarify action; clarify is allowed max once per skill, forcing next if attempted again."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # Vague answer (<15 words) on Python anchor
    state, _ = step(state, TurnEnd(text="We use asyncio and multiprocessing in our services.", turn_id="t_vague", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    clarify_q = "Could you share a concrete example of using asyncio from your work?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "clarify",
                "followup": clarify_q,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    assert state.clarify_used_per_skill["Python"] is True
    assert state.followups_used_per_skill["Python"] == 1
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    assert clarify_q in speak_eff.text

    # Candidate answers clarify, and decision tries to clarify a SECOND time on same skill
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=6500))
    state, _ = step(state, TurnEnd(text="Just regular async tasks.", turn_id="t_vague_2", now_ms=7000))
    # 4 words -> INCOMPLETE, grace is 2500ms -> commits at 7000 + 2500 = 9500ms
    state, effects = step(state, Tick(now_ms=9600))
    req2 = next(e for e in effects if isinstance(e, RequestDecision))

    state, effects = step(
        state,
        DecisionReady(
            token=req2.token,
            decision={
                "ack": "Understood.",
                "action": "clarify",
                "followup": "Can you give another example of asyncio?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=9700,
        ),
    )
    # Clarify max once per skill rule forces action to 'next'!
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.skill_names[state.current_skill_index] == "Distributed Systems"


# -----------------------------------------------------------------------------
# Test 26: Phase A2 - Deterministic Fallback Uses Clarify and Never Escalation
# -----------------------------------------------------------------------------
def test_deterministic_fallback_uses_clarify_and_never_escalation():
    """Fallback for vague/short answer with no probe match uses templated clarify once, and NEVER escalation."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # Candidate gives a short 4-word answer with NO keyword overlap to probe triggers
    short_answer = "We use both methods."
    state, _ = step(state, TurnEnd(text=short_answer, turn_id="t_short", now_ms=5500))
    # 4 words -> INCOMPLETE, grace is 2500ms -> commits at 5500 + 2500 = 8000ms
    state, effects = step(state, Tick(now_ms=8100))
    assert state.awaiting_decision is True

    # 1500ms timeout occurs without DecisionReady (8100 + 1500 = 9600ms)
    state, fallback_effects = step(state, Tick(now_ms=9600))
    assert state.awaiting_decision is False
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    assert state.clarify_used_per_skill["Python"] is True
    speak_eff = next(e for e in fallback_effects if isinstance(e, Speak))
    assert "Could you share a concrete example from your work demonstrating that?" in speak_eff.text
    # Explicitly assert escalation question was NOT picked
    escalation_q = next(q for q in state.questions if q.kind == "escalation" and q.skill_name == "Python")
    assert speak_eff.question_text != escalation_q.question_text


# -----------------------------------------------------------------------------
# Test 27: Phase A2 - Acks Appear in Every Spoken Reply Including Intro
# -----------------------------------------------------------------------------
def test_acks_appear_in_every_spoken_reply_including_intro():
    """Acks appear in every spoken reply, including the intro answer which references candidate's words."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Candidate answers intro with specific engineering background
    intro_ans = "I have five years of backend engineering experience with Python and distributed systems."
    state, _ = step(state, TurnEnd(text=intro_ans, turn_id="t_intro", now_ms=4000))
    state, effects = step(state, Tick(now_ms=4300))
    intro_req = next(e for e in effects if isinstance(e, RequestDecision))
    anchor_q = state.skill_questions.get("Python", {}).get("anchor")
    intro_ack = "Thanks for sharing your backend engineering background."
    state, dec_effects = step(
        state,
        DecisionReady(
            token=intro_req.token,
            decision={
                "action": "new_topic",
                "ack": intro_ack,
                "target_skill": "Python",
                "question": anchor_q.question_text if anchor_q else "",
            },
            now_ms=4400,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    speak_eff = next(e for e in dec_effects if isinstance(e, Speak))
    # Spoken text must contain the ack
    assert speak_eff.ack_text != ""
    assert speak_eff.ack_text in speak_eff.text
    assert "backend" in speak_eff.ack_text.lower() or "python" in speak_eff.ack_text.lower() or "engineering" in speak_eff.ack_text.lower()

    # Next, candidate answers anchor and gets a decision with an ack
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=5000))
    state, _ = step(state, TurnEnd(text="We use asyncio event loop for web sockets.", turn_id="t_anchor", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "That makes sense for web sockets.",
                "action": "probe",
                "followup": "Can you elaborate on web socket connection drops?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak_eff2 = next(e for e in effects if isinstance(e, Speak))
    assert speak_eff2.ack_text == "That makes sense for web sockets."
    assert "That makes sense for web sockets." in speak_eff2.text


# -----------------------------------------------------------------------------
# Test 28: Phase A2 - Candidate Q&A Known Fact, Unknown Fact Deferral & Close on 'No'
# -----------------------------------------------------------------------------
def test_candidate_qa_known_fact_unknown_fact_and_close_on_no():
    """Candidate Q&A answers from job record facts, defers unknown facts without inventing, and closes on 'no'."""
    plan = make_test_plan()
    plan["job_record"] = {
        "title": "Senior Distributed Systems Engineer",
        "seniority": "Senior",
        "skills": ["Python", "asyncio", "Kafka", "PostgreSQL"],
        "description": "Designing high-scale streaming pipelines.",
    }
    state, _ = step(ConductorState(), SessionStart(session_id="test_qa", plan=plan, now_ms=1000))

    # Fast forward to Candidate Q&A
    state.phase = ConductorPhase.CANDIDATE_QA
    qa_q = next(q for q in state.questions if q.kind == "candidate_qa")
    state.current_question_index = qa_q.question_index
    state.job_record = plan["job_record"]

    # Round 1: Candidate asks about seniority level (known fact)
    state, _ = step(state, TurnEnd(text="What seniority level is this role targeted at?", turn_id="t_q1", now_ms=2000))
    state, effects = step(state, Tick(now_ms=2300))
    assert state.awaiting_decision is True
    assert state.qa_rounds_used == 1
    req1 = next(e for e in effects if isinstance(e, RequestDecision))

    known_answer = "This role is for a Senior level engineer. Anything else?"
    state, effects = step(
        state,
        DecisionReady(
            token=req1.token,
            decision={
                "ack": "",
                "action": "qa_reply",
                "followup": known_answer,
            },
            now_ms=2400,
        ),
    )
    assert state.phase == ConductorPhase.CANDIDATE_QA
    speak_eff1 = next(e for e in effects if isinstance(e, Speak))
    assert speak_eff1.text == known_answer

    # Round 2: Candidate asks about compensation (unknown fact not in job record -> deferral)
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state, _ = step(state, TurnEnd(text="What is the base salary and equity range for this position?", turn_id="t_q2", now_ms=3500))
    state, effects = step(state, Tick(now_ms=3800))
    assert state.qa_rounds_used == 2
    req2 = next(e for e in effects if isinstance(e, RequestDecision))

    deferral_answer = "I don't have that detail in our job description, but our hiring team will follow up with you on that. Anything else?"
    state, effects = step(
        state,
        DecisionReady(
            token=req2.token,
            decision={
                "ack": "",
                "action": "qa_reply",
                "followup": deferral_answer,
            },
            now_ms=3900,
        ),
    )
    assert state.phase == ConductorPhase.CANDIDATE_QA
    speak_eff2 = next(e for e in effects if isinstance(e, Speak))
    assert "I don't have that detail in our job description" in speak_eff2.text
    assert "hiring team will follow up" in speak_eff2.text

    # Round 3: Candidate says 'no, that's all' -> closes immediately
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=4500))
    state, _ = step(state, TurnEnd(text="No, that's all, thank you!", turn_id="t_q3", now_ms=5000))
    # 5 words -> INCOMPLETE, grace is 2500ms -> commits at 5000 + 2500 = 7500ms
    state, effects = step(state, Tick(now_ms=7600))
    assert state.phase == ConductorPhase.CLOSING
    speak_eff3 = next(e for e in effects if isinstance(e, Speak))
    assert "Thank you" in speak_eff3.text


# -----------------------------------------------------------------------------
# Test 29: Phase A2 - Candidate Q&A Max 3 Rounds
# -----------------------------------------------------------------------------
def test_candidate_qa_max_three_rounds():
    """Candidate Q&A allows at most 3 questions from candidate before wrapping up to CLOSING."""
    plan = make_test_plan()
    plan["job_record"] = {"title": "Software Engineer"}
    state, _ = step(ConductorState(), SessionStart(session_id="test_qa_max", plan=plan, now_ms=1000))
    state.phase = ConductorPhase.CANDIDATE_QA
    state.job_record = plan["job_record"]
    state.qa_rounds_used = 3  # 3 rounds already used

    # Candidate asks a 4th question
    state, _ = step(state, TurnEnd(text="Can you tell me about the team culture?", turn_id="t_q4", now_ms=2000))
    state, effects = step(state, Tick(now_ms=2300))
    # Exceeded max 3 rounds -> transitions directly to CLOSING
    assert state.phase == ConductorPhase.CLOSING
    assert any(isinstance(e, Speak) for e in effects)


# -----------------------------------------------------------------------------
# Test 30: Phase A2 - Mid-Interview Clarification (Rephrase Intent Pattern)
# -----------------------------------------------------------------------------
def test_mid_interview_clarification_rephrase_pattern():
    """If candidate asks 'can you rephrase?', conductor rephrases question without consuming follow-up count."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    orig_q_index = state.current_question_index

    # Candidate asks: "Can you rephrase the question?"
    state, effects = step(state, TurnEnd(text="Can you rephrase the question please?", turn_id="t_rephrase", now_ms=5500))
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    # Follow-ups used must NOT be incremented
    assert state.followups_used_per_skill["Python"] == 0
    # Question index stays the same
    assert state.current_question_index == orig_q_index
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    assert "Sure, let me rephrase that." in speak_eff.text

    # Candidate then answers the rephrased question; answer is attributed to the original question!
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=6500))
    state, _ = step(state, TurnEnd(text="We use asyncio for cooperative multitasking with coroutines.", turn_id="t_ans", now_ms=7000))
    state, effects = step(state, Tick(now_ms=7300))
    persist_eff = next(e for e in effects if isinstance(e, Persist))
    assert persist_eff.turn["question_index"] == orig_q_index


# -----------------------------------------------------------------------------
# Test 31: Phase A2 - Mid-Interview Clarification (Decision Action Rephrase)
# -----------------------------------------------------------------------------
def test_mid_interview_clarification_decision_action_rephrase():
    """Decision action 'rephrase' rephrases in simpler words without incrementing follow-up count."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    orig_q_index = state.current_question_index

    # Candidate says something indicating confusion
    state, _ = step(state, TurnEnd(text="I am not quite sure what you are asking there.", turn_id="t_confused", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    rephrased_q = "In simpler words, when would you choose asyncio over multiprocessing in Python?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "No problem.",
                "action": "rephrase",
                "followup": rephrased_q,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    # Stays on SKILL_ANCHOR, question_index unchanged, followups_used NOT incremented
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.current_question_index == orig_q_index
    assert state.followups_used_per_skill["Python"] == 0
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    assert rephrased_q in speak_eff.text
    assert speak_eff.ack_text == "No problem."


# -----------------------------------------------------------------------------
# Phase A3 Tests: Defect Resolution & Agentic Interview Polish
# -----------------------------------------------------------------------------

def _advance_to_skill_anchor(custom_plan: Dict[str, Any] = None) -> Tuple[ConductorState, RequestDecision]:
    """Helper to advance state to Python SKILL_ANCHOR and commit an answer."""
    state, _ = start_session(plan=custom_plan)
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state, _ = step(state, TurnEnd(text="I have five years of backend engineering experience with Python.", turn_id="t_intro", now_ms=4000))
    state, effects = step(state, Tick(now_ms=4300))
    intro_req = next((e for e in effects if isinstance(e, RequestDecision)), None)
    if intro_req:
        anchor_q = state.skill_questions.get("Python", {}).get("anchor")
        state, _ = step(
            state,
            DecisionReady(
                token=intro_req.token,
                decision={
                    "action": "new_topic",
                    "ack": "Thanks for sharing.",
                    "target_skill": "Python",
                    "question": anchor_q.question_text if anchor_q else "",
                },
                now_ms=4400,
            ),
        )
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=5000))
    # Candidate answers anchor question
    state, _ = step(state, TurnEnd(text="We use asyncio for concurrency with event loop and celery for background workers.", turn_id="t_ans_anchor", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))
    return state, req


def test_phase_a3_spoken_ack_probe():
    """Assert ack text is inside text sent to TTS for action 'probe'."""
    state, req = _advance_to_skill_anchor()
    state.last_ack_opener = None
    ack = "Right, event loops handle high IO concurrency."
    q_text = "How do you configure Celery worker concurrency with asyncio or threads?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "probe",
                "probe_id": "probe_celery",
                "followup": q_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert ack in speak.text
    assert q_text in speak.text
    assert speak.text == f"{ack} {q_text}"
    assert speak.ack_text == ack


def test_phase_a3_spoken_ack_clarify():
    """Assert ack text is inside text sent to TTS for action 'clarify'."""
    state, req = _advance_to_skill_anchor()
    ack = "I see, asynchronous coroutines require careful error handling."
    q_text = "Could you share a concrete example from your work demonstrating that?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "clarify",
                "followup": q_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert ack in speak.text
    assert q_text in speak.text
    assert speak.text == f"{ack} {q_text}"
    assert speak.ack_text == ack


def test_phase_a3_spoken_ack_escalate():
    """Assert ack text is inside text sent to TTS for action 'escalate'."""
    state, req = _advance_to_skill_anchor()
    ack = "That makes sense, separating CPU tasks from the main thread."
    q_text = "What specific profiling tools have you used to find CPU bottlenecks in a Python service?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "escalate",
                "followup": q_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert ack in speak.text
    assert q_text in speak.text
    assert "Let me take that a bit further." in speak.text
    assert speak.text == f"{ack} Let me take that a bit further. {q_text}"
    assert speak.ack_text == ack


def test_phase_a3_spoken_ack_hypothetical():
    """Assert ack text is inside text sent to TTS for action 'hypothetical'."""
    state, req = _advance_to_skill_anchor()
    ack = "Interesting, starting from core architectural trade-offs."
    q_text = "Can you explain how the GIL affects CPU-bound versus I/O-bound tasks in Python?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "hypothetical",
                "followup": q_text,
                "covered_expectations": [],
                "no_experience": True,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert ack in speak.text
    assert q_text in speak.text
    assert speak.text == f"{ack} {q_text}"
    assert speak.ack_text == ack


def test_phase_a3_spoken_ack_next():
    """Assert ack text is inside text sent to TTS for action 'next'."""
    state, req = _advance_to_skill_anchor()
    state.last_ack_opener = None
    ack = "Right, that covers the core concurrency models."
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "next",
                "followup": "",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert ack in speak.text
    assert speak.ack_text == ack
    assert "Distributed Systems" in speak.text or "retry" in speak.text


def test_phase_a3_spoken_ack_off_topic():
    """Assert ack text is inside text sent to TTS for action 'off_topic'."""
    state, req = _advance_to_skill_anchor()
    ack = "I see, though staying focused helps us assess this skill."
    q_text = "Could you share your thoughts on handling concurrency in Python using asyncio?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "off_topic",
                "followup": q_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert ack in speak.text
    assert q_text in speak.text
    assert speak.text == f"{ack} Let's come back to it. {q_text}"
    assert speak.ack_text == ack


def test_phase_a3_spoken_ack_rephrase():
    """Assert ack text is inside text sent to TTS for action 'rephrase'."""
    state, req = _advance_to_skill_anchor()
    ack = "No problem, let's look at this from another perspective."
    q_text = "In simpler words, when would you choose asyncio over multiprocessing in Python?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "rephrase",
                "followup": q_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert ack in speak.text
    assert q_text in speak.text
    assert speak.text == f"{ack} {q_text}"
    assert speak.ack_text == ack


def test_phase_a3_spoken_ack_qa_reply():
    """Assert ack text is inside text sent to TTS for action 'qa_reply' in Candidate Q&A."""
    plan = make_test_plan()
    plan["job_record"] = {"title": "Senior Python Engineer", "team": "Platform"}
    state, _ = start_session(plan=plan)
    # Fast forward to CANDIDATE_QA phase
    state.phase = ConductorPhase.CANDIDATE_QA
    qa_q = next(q for q in state.questions if q.kind == "candidate_qa")
    state.current_question_index = qa_q.question_index
    state.current_skill_index = len(state.skill_names)

    # Candidate asks about career growth
    state, _ = step(state, TurnEnd(text="What does career advancement look like on this team?", turn_id="t_qa_1", now_ms=10000))
    state, effects = step(state, Tick(now_ms=10300))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    ack = "Right, career growth is an important consideration."
    ans_text = "Engineers advance through ownership of large architecture systems and mentoring."
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "qa_reply",
                "followup": ans_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=10500,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert ack in speak.text
    assert ans_text in speak.text
    assert speak.ack_text == ack
    assert speak.text.startswith(ack)


def test_phase_a3_spoken_ack_suppressed_when_bridge_played():
    """When a bridge clip actually played, ack is dropped from spoken reply."""
    state, req = _advance_to_skill_anchor()
    # Mark bridge as having played for this commit
    state.bridge_played_for_commit = True

    ack = "Right, event loops handle high IO concurrency."
    q_text = "How do you configure Celery worker concurrency with asyncio or threads?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "probe",
                "probe_id": "probe_celery",
                "followup": q_text,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    # Phase A4 Bridge Redesign: still speak the ack, but strip leading opener ('Right, ')
    assert not speak.text.startswith("Right,")
    assert speak.text == f"Event loops handle high IO concurrency. {q_text}"
    assert speak.ack_text == "Event loops handle high IO concurrency."


def test_phase_a3_off_topic_first_retry_stays_on_same_question():
    """First off-topic answer re-asks the SAME current question and stays on the same skill."""
    state, req = _advance_to_skill_anchor()
    orig_q_index = state.current_question_index
    orig_skill = state.skill_names[state.current_skill_index]

    ack = "Understood."
    retry_q = "Could you share your thoughts on handling concurrency in Python using asyncio?"
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "off_topic",
                "followup": retry_q,
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    # Stays on same skill and same question
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.current_question_index == orig_q_index
    assert state.skill_names[state.current_skill_index] == orig_skill
    assert state.off_topic_retries_per_question[orig_q_index] == 1

    speak = next(e for e in effects if isinstance(e, Speak))
    assert retry_q in speak.text
    assert ack in speak.text


def test_phase_a3_off_topic_second_retry_advances_with_neutral_line():
    """Second consecutive off-topic answer on same question speaks a neutral line and advances."""
    state, req = _advance_to_skill_anchor()
    orig_q_index = state.current_question_index

    # First off-topic answer
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "off_topic",
                "followup": "Could you share your thoughts on Python concurrency?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    assert state.off_topic_retries_per_question[orig_q_index] == 1

    # Bot finishes speaking retry question
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=6500))

    # Candidate gives a second off-topic answer
    state, _ = step(state, TurnEnd(text="The weather in San Francisco is really nice today.", turn_id="t_ans_off2", now_ms=7000))
    state, effects = step(state, Tick(now_ms=7300))
    req2 = next(e for e in effects if isinstance(e, RequestDecision))

    # Decision still says off_topic
    state, effects = step(
        state,
        DecisionReady(
            token=req2.token,
            decision={
                "ack": "Understood.",
                "action": "off_topic",
                "followup": "Could you answer the concurrency question?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=7400,
        ),
    )
    # Conductor must advance to next skill with neutral line
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.current_skill_index == 1  # Distributed Systems
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "No problem, let's move on to the next topic." in speak.text
    assert "Understood." in speak.text


def test_phase_a3_candidate_qa_closing_and_completion():
    """Candidate saying 'no' or 'that is all' transitions to CLOSING with closing text, then COMPLETED."""
    plan = make_test_plan()
    plan["job_record"] = {"title": "Software Engineer"}
    state, _ = start_session(plan=plan)
    state.phase = ConductorPhase.CANDIDATE_QA
    qa_q = next(q for q in state.questions if q.kind == "candidate_qa")
    state.current_question_index = qa_q.question_index
    state.current_skill_index = len(state.skill_names)
    state.bot_speaking = False
    state.active_speech_id = None

    # Candidate says "No, that's all, thank you!"
    state, _ = step(state, TurnEnd(text="No, that's all, thank you!", turn_id="t_done", now_ms=10000))
    state, effects = step(state, Tick(now_ms=13000))

    # Conductor transitions to CLOSING
    assert state.phase == ConductorPhase.CLOSING
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "Thank you for speaking with us today." in speak.text
    assert "We will now move on" not in speak.text

    # When closing speech completes -> COMPLETED
    state, effects = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=15000))
    assert state.phase == ConductorPhase.COMPLETED
    assert any(isinstance(e, EmitUI) and e.status == "completed" for e in effects)


def test_phase_a3_ack_opener_rotation():
    """When decision uses the same opener twice in a row, conductor swaps it to avoid repetition."""
    state, req = _advance_to_skill_anchor()
    state.last_ack_opener = "Right,"

    # Decision tries to use "Right," again
    ack = "Right, asynchronous tasks avoid blocking thread pools."
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": ack,
                "action": "probe",
                "probe_id": "probe_celery",
                "followup": "How do you configure Celery worker concurrency with asyncio or threads?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    # Must have replaced "Right," with another valid opener
    assert not speak.text.startswith("Right,")
    assert any(speak.text.startswith(op) for op in ["I see,", "Okay,", "Mm,", "So,"])
    assert state.last_ack_opener != "Right,"


def test_phase_a3_strong_answer_stretch_escalation():
    """When core expectations are covered, stretch are uncovered, and time > 120s, escalate to stretch."""
    plan = make_test_plan()
    # Add stretch expectations to Python anchor
    for q in plan["questions"]:
        if q["question_index"] == 2:
            q["expected_key_points"] = ["asyncio", "multiprocessing"]
            q["stretch_key_points"] = ["cpython profiling", "memory leak debugging"]

    state, req = _advance_to_skill_anchor(custom_plan=plan)
    # LLM decision returns all core expectations covered
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Right, dividing workloads across processes avoids GIL stalls.",
                "action": "next",  # LLM proposed next
                "covered_expectations": ["asyncio", "multiprocessing"],
                "followup": "",
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    # Conductor overrides to escalate because stretch expectations remain uncovered!
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "profiling tools" in speak.text
    assert state.escalation_used_for_skill["Python"] is True


def test_phase_a3_second_no_experience_advances_with_warm_transition():
    """First no_experience gives hypothetical; second no_experience says 'No problem, let's move on.' and advances."""
    state, req = _advance_to_skill_anchor()

    # Turn 1: First no_experience -> hypothetical
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "hypothetical",
                "followup": "Can you explain how the GIL affects CPU-bound versus I/O-bound tasks in Python?",
                "covered_expectations": [],
                "no_experience": True,
            },
            now_ms=5900,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP
    assert state.hypothetical_used_per_skill["Python"] is True

    # Bot finishes asking hypothetical question
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=6500))

    # Turn 2: Candidate answers hypothetical with no_experience again
    state, _ = step(state, TurnEnd(text="I haven't worked with GIL internals either, no experience.", turn_id="t_hypo_no", now_ms=7000))
    state, effects = step(state, Tick(now_ms=7300))
    req2 = next(e for e in effects if isinstance(e, RequestDecision))

    state, effects = step(
        state,
        DecisionReady(
            token=req2.token,
            decision={
                "ack": "Understood.",
                "action": "hypothetical",
                "followup": "Can you explain how the GIL affects CPU-bound versus I/O-bound tasks in Python?",
                "covered_expectations": [],
                "no_experience": True,
            },
            now_ms=7400,
        ),
    )
    # Conductor must advance to next skill with warm neutral line
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.current_skill_index == 1  # Distributed Systems
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "No problem, let's move on." in speak.text
    assert "Understood." in speak.text


def test_phase_a3_welcome_spoken_script_role_title_and_duration():
    """Greeting spoken script formats role title naturally."""
    plan = make_test_plan()
    # Remove canned welcome text to test fallback template
    for q in plan["questions"]:
        if q["kind"] == "welcome":
            q["question_text"] = ""
    plan["job_record"] = {"title": "Staff Platform Architect"}
    plan["duration_planned_mins"] = 40

    state = ConductorState()
    state, effects = step(state, SessionStart(session_id="test_welcome_a3", plan=plan, now_ms=1000))
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "Staff Platform Architect" in speak.text
    assert "Thanks for making the time today" in speak.text
    assert "How are you?" in speak.text


# -----------------------------------------------------------------------------
# Phase A4 Dedicated Unit Tests
# -----------------------------------------------------------------------------

def test_phase_a4_ack_first_streaming():
    """AckReady emits SpeakAck immediately and cancels pending bridge timer."""
    state, req = _advance_to_skill_anchor()
    assert "bridge" in state.active_timers

    ack_text = "I see, asyncio handles high throughput socket connections."
    state, effects = step(state, AckReady(token=req.token, text=ack_text, now_ms=5600))
    speak_ack = next(e for e in effects if isinstance(e, SpeakAck))
    assert speak_ack.token == req.token
    assert speak_ack.text == ack_text
    assert state.spoken_ack_token == req.token
    assert state.spoken_ack_text == ack_text
    # Bridge timer must be cancelled immediately
    assert "bridge" not in state.active_timers


def test_phase_a4_decision_arrives_while_ack_playing_defers_to_speech_done():
    """If DecisionReady arrives while ack is playing, question speech is held until BotSpeechDone."""
    state, req = _advance_to_skill_anchor()
    ack_text = "I see, asyncio handles high throughput socket connections."
    state, effects1 = step(state, AckReady(token=req.token, text=ack_text, now_ms=5600))
    ack_eff = next(e for e in effects1 if isinstance(e, SpeakAck))

    # Decision arrives at 5800ms while ack is still playing (bot_speaking=True)
    decision = {
        "ack": ack_text,
        "action": "probe",
        "probe_id": "probe_celery",
        "followup": "How do you configure Celery worker concurrency with asyncio or threads?",
        "covered_expectations": [],
        "no_experience": False,
    }
    state, effects2 = step(state, DecisionReady(token=req.token, decision=decision, now_ms=5800))
    # No Speak effect emitted yet because ack is playing
    assert not any(isinstance(e, Speak) for e in effects2)
    assert len(state.pending_question_effects) > 0

    # Ack finishes playing at 6200ms -> BotSpeechDone fires -> emits Speak immediately
    state, effects3 = step(state, BotSpeechDone(speech_id=ack_eff.speech_id, now_ms=6200))
    speak_eff = next(e for e in effects3 if isinstance(e, Speak))
    assert speak_eff.question_text == decision["followup"]
    # Ack was already spoken so it's not repeated in Speak.text
    assert speak_eff.text == decision["followup"]
    assert speak_eff.ack_text == ack_text


def test_phase_a4_bridge_cancelled_if_ack_started():
    """Bridge timer fires at 700ms, but if ack already started, bridge does NOT play."""
    state, req = _advance_to_skill_anchor()
    state, _ = step(state, AckReady(token=req.token, text="Right, asynchronous event loops.", now_ms=5400))
    assert state.spoken_ack_token == req.token

    # 700ms Tick fires
    state, effects = step(state, Tick(now_ms=5800))
    assert not any(isinstance(e, PlayBridge) for e in effects)


def test_phase_a4_ack_validator_rejects_praise():
    """Ack Validator rejects praise and quality evaluation words."""
    state, req = _advance_to_skill_anchor()
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Great, that was an excellent and solid approach to concurrency.",
                "action": "probe",
                "probe_id": "probe_celery",
                "followup": "How do you configure Celery worker concurrency with asyncio or threads?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "great" not in speak.text.lower()
    assert "excellent" not in speak.text.lower()
    assert "solid" not in speak.text.lower()


def test_phase_a4_transitions_next_skill():
    """When action is 'next' and moving to a new skill, prepend deterministic 'Let's move on to {skill name}.'"""
    state, req = _advance_to_skill_anchor()
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Right, event loops handle I/O tasks.",
                "action": "next",
                "followup": "",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "Let's move on to Distributed Systems." in speak.text


def test_phase_a4_off_topic_reask_prefix():
    """Off-topic follow-up must be prefixed with 'Let's come back to it. ' and share >=3 content words."""
    state, req = _advance_to_skill_anchor()
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "I see, let's keep to the topic.",
                "action": "off_topic",
                "followup": "Could you share your thoughts on handling concurrency in Python using asyncio?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "Let's come back to it." in speak.text


def test_phase_a4_two_off_topic_marks_insufficient_evidence():
    """If a skill has 2 off-topic turns, mark insufficient_evidence_per_skill and advance to next skill."""
    state, req = _advance_to_skill_anchor()
    curr_skill = state.skill_names[state.current_skill_index]

    # First off-topic retry
    state, _ = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "Understood.",
                "action": "off_topic",
                "followup": "Could you share your thoughts on handling concurrency in Python using asyncio?",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=5900,
        ),
    )
    assert not state.insufficient_evidence_per_skill.get(curr_skill, False)

    # Next candidate answer is also off-topic on the same skill
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=6200))
    state, _ = step(state, TurnEnd(text="I also enjoy writing front-end CSS animations.", turn_id="t_off2", now_ms=6500))
    state, effects = step(state, Tick(now_ms=6800))
    req2 = next(e for e in effects if isinstance(e, RequestDecision))

    # Second off-topic decision arrives
    state, effects2 = step(
        state,
        DecisionReady(
            token=req2.token,
            decision={
                "ack": "Understood.",
                "action": "off_topic",
                "followup": "",
                "covered_expectations": [],
                "no_experience": False,
            },
            now_ms=7000,
        ),
    )
    # Marked insufficient evidence for Python
    assert state.insufficient_evidence_per_skill[curr_skill] is True
    # Advanced to next skill
    assert state.skill_names[state.current_skill_index] == "Distributed Systems"


# -----------------------------------------------------------------------------
# Phase A5: Ack Grounding & Verification Tests
# -----------------------------------------------------------------------------

def test_phase_a5_is_ack_grounded_positive():
    """Ack sharing >=1 content word with candidate answer that is NOT in current question passes grounding."""
    from backend.app.services.interview_v2.conductor import is_ack_grounded

    q_text = "How do you handle concurrency in Python using asyncio versus multiprocessing?"
    cand_ans = "In our architecture we deployed Kafka streaming consumers and Redis caching."
    ack = "Right, so your Kafka streaming consumers."
    assert is_ack_grounded(ack, cand_ans, q_text) is True


def test_phase_a5_is_ack_grounded_negative_echoing_question_only():
    """Ack that only repeats words present in the question without candidate-novel words fails grounding."""
    from backend.app.services.interview_v2.conductor import is_ack_grounded

    q_text = "How do you handle concurrency in Python using asyncio versus multiprocessing?"
    cand_ans = "We use concurrency in Python."
    ack = "Right, concurrency in Python."
    assert is_ack_grounded(ack, cand_ans, q_text) is False


def test_phase_a5_is_ack_grounded_negative_hallucinated():
    """Ack mentioning unrelated or hallucinated topics not in candidate answer fails grounding."""
    from backend.app.services.interview_v2.conductor import is_ack_grounded

    q_text = "How do you handle concurrency in Python using asyncio versus multiprocessing?"
    cand_ans = "We use non-blocking event loops for network I/O."
    ack = "Right, relational PostgreSQL partitioning."
    assert is_ack_grounded(ack, cand_ans, q_text) is False


def test_phase_a5_validate_and_format_ack_enforces_grounding():
    """validate_and_format_ack returns empty string if enforce_grounding=True and ack is ungrounded."""
    from backend.app.services.interview_v2.conductor import validate_and_format_ack

    q_text = "How do you handle concurrency in Python using asyncio versus multiprocessing?"
    cand_ans = "We use non-blocking event loops for network I/O."
    ungrounded_ack = "Right, relational PostgreSQL partitioning."

    formatted, opener = validate_and_format_ack(
        raw_ack=ungrounded_ack,
        last_opener=None,
        candidate_answer=cand_ans,
        question_text=q_text,
        enforce_grounding=True,
    )
    assert formatted == ""







# -----------------------------------------------------------------------------
# Test: No-Knowledge Guard (candidate says "I don't know")
# -----------------------------------------------------------------------------

def test_no_knowledge_answer_never_probed():
    """An 'I don't know' answer coerces any follow_up/clarify decision into the
    anchor_alt swap, and a second admission moves on with a gracious transition."""
    state, _ = start_session()
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    state = complete_intro_and_advance(state)
    assert state.phase == ConductorPhase.SKILL_ANCHOR

    # First admission: "I don't know"
    state, _ = step(state, TurnEnd(text="I don't know, I have never worked with Python concurrency.", turn_id="t_dk1", now_ms=5500))
    state, effects = step(state, Tick(now_ms=5800))
    req = next(e for e in effects if isinstance(e, RequestDecision))

    alt_q = next(q for q in state.questions if q.kind == "anchor_alt" and q.skill_name == "Python")
    # Model wrongly decides to probe deeper into the unknown topic:
    state, effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "ack": "",
                "action": "follow_up",
                "followup": "Can you explain threading locks anyway?",
                "covered_expectations": [],
            },
            now_ms=5900,
        ),
    )
    speak_eff = next(e for e in effects if isinstance(e, Speak))
    assert "threading locks" not in speak_eff.text, "must never probe an admission of no knowledge"
    assert alt_q.question_text in speak_eff.text, "must swap to the prepared alternative question"
    assert "No problem" in speak_eff.text
    assert state.hypothetical_used_per_skill.get("Python") is True

    # Second admission on the same skill: move on gracefully instead of swapping again
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=7000))
    state, _ = step(state, TurnEnd(text="Honestly, I have no idea about that one.", turn_id="t_dk2", now_ms=9000))
    state, effects = step(state, Tick(now_ms=9300))
    req2 = next(e for e in effects if isinstance(e, RequestDecision))
    state, effects = step(
        state,
        DecisionReady(
            token=req2.token,
            decision={"ack": "", "action": "follow_up", "followup": "What about locks?", "covered_expectations": []},
            now_ms=9400,
        ),
    )
    speak2 = next(e for e in effects if isinstance(e, Speak))
    assert "What about locks?" not in speak2.text
    assert "move on" in speak2.text.lower()
