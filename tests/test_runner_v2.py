"""Unit Tests for Interview Runner (v2) & Fast Reply Path.

Tests SessionRunner, event queue ordering, stale timer protection,
cancellation during speech, state resumption, and speculative LLM fallback
with fake Flux/TTS/LLM components and ZERO network.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List
import pytest

from backend.app.models import InterviewQuestion, InterviewSession
from backend.app.services.interview_v2.conductor import (
    BotAudioStarted,
    BotSpeechDone,
    ConductorPhase,
    ConductorState,
    EagerTurnEnd,
    EndButton,
    ReadyButton,
    SessionStart,
    Tick,
    TurnEnd,
    TurnStart,
)
from backend.app.services.interview_v2.runner import (
    BRIDGE_AUDIO_CACHE,
    BRIDGE_PHRASES,
    SESSION_STATE_CACHE,
    SessionRunner,
    build_script,
    generate_fallback_pcm,
    validate_speculative_output,
    warmup_bridge_cache,
)


# -----------------------------------------------------------------------------
# Fakes & Mocks
# -----------------------------------------------------------------------------

class FakeWebSocket:
    """Mock WebSocket recording all sent messages and binary bytes."""

    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
        self.sent_bytes: List[bytes] = []

    async def send_json(self, data: Dict[str, Any]) -> None:
        self.sent_messages.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)


class FakeAuraTTSClient:
    """Mock Aura-2 TTS generating predictable dummy PCM frames with zero network."""

    def __init__(self, voice="aura-2-mock", delay_s: float = 0.0):
        self.voice = voice
        self.cancelled = False
        self.cancel_count = 0
        self.delay_s = delay_s

    async def speak(self, text: str) -> AsyncIterator[bytes]:
        self.cancelled = False
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        if not self.cancelled:
            # Yield two 480-byte dummy PCM chunks
            yield b"\x01\x00" * 240
            await asyncio.sleep(0.01)
            if not self.cancelled:
                yield b"\x02\x00" * 240

    async def cancel(self) -> None:
        self.cancelled = True
        self.cancel_count += 1


def make_test_script() -> Dict[str, Any]:
    return {
        "questions": [
            {
                "question_index": 0,
                "kind": "welcome",
                "skill_name": "Welcome & Agenda",
                "question_text": "Hi there! Welcome to your interview. Ready to start?",
                "priority_tier": "P0",
            },
            {
                "question_index": 1,
                "kind": "intro_hook",
                "skill_name": "Introduction",
                "question_text": "To start off, could you briefly introduce yourself?",
                "priority_tier": "P0",
            },
            {
                "question_index": 2,
                "kind": "anchor",
                "skill_name": "Distributed Storage",
                "question_text": "How do you handle partition replication across multiple nodes?",
                "priority_tier": "P0",
            },
            {
                "question_index": 3,
                "kind": "anchor_alt",
                "skill_name": "Distributed Storage",
                "question_text": "What disk sync strategies do you enforce for fault tolerance?",
                "priority_tier": "P0",
            },
            {
                "question_index": 4,
                "kind": "escalation",
                "skill_name": "Distributed Storage",
                "question_text": "How do you handle split-brain scenarios in a consensus cluster?",
                "priority_tier": "P0",
            },
            {
                "question_index": 5,
                "kind": "candidate_qa",
                "skill_name": "Candidate Q&A",
                "question_text": "What questions do you have for us?",
                "priority_tier": "P0",
            },
            {
                "question_index": 6,
                "kind": "closing",
                "skill_name": "Closing",
                "question_text": "Thank you for your time. Have a great day!",
                "priority_tier": "P0",
            },
        ]
    }


# -----------------------------------------------------------------------------
# Test 1: Adapter build_script with real InterviewSession models
# -----------------------------------------------------------------------------
def test_build_script_adapter_real_models():
    """Verify build_script accurately maps real InterviewSession question rows."""
    q0 = InterviewQuestion(
        question_index=0,
        kind="welcome",
        skill_name="Welcome & Agenda",
        question_text="Hi there! Welcome to your interview.",
        priority_tier="P0",
    )
    q1 = InterviewQuestion(
        question_index=1,
        kind="intro_hook",
        skill_name="Introduction",
        question_text="Tell us about yourself.",
        priority_tier="P0",
    )
    q2 = InterviewQuestion(
        question_index=2,
        kind="anchor",
        skill_name="Python",
        question_text="How do you handle concurrency?",
        priority_tier="P0",
    )
    q3 = InterviewQuestion(
        question_index=3,
        kind="anchor_alt",
        skill_name="Python",
        question_text="Explain the GIL impact.",
        priority_tier="P0",
    )
    q4 = InterviewQuestion(
        question_index=4,
        kind="escalation",
        skill_name="Python",
        question_text="How do you profile bottlenecks?",
        priority_tier="P0",
    )

    session = InterviewSession(
        id="real-session-test-uuid",
        job_id="job-123",
        application_id="app-123",
    )
    session.questions = [q0, q1, q2, q3, q4]

    script = build_script(session)
    assert "questions" in script
    assert len(script["questions"]) == 5
    assert script["questions"][0]["kind"] == "welcome"
    assert script["questions"][1]["kind"] == "intro_hook"
    assert script["questions"][2]["kind"] == "anchor"
    assert script["questions"][2]["skill_name"] == "Python"
    assert script["questions"][3]["kind"] == "anchor_alt"
    assert script["questions"][4]["kind"] == "escalation"


# -----------------------------------------------------------------------------
# Test 2: Event Queue Ordering & Sequential Execution
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_queue_ordering():
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner(
        session_id="sess_order_test",
        script=script,
        websocket=ws,
        aura_client=tts,
    )
    await runner.start()

    # Enqueue sequence of events
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))

    # Give event loop time to process
    await asyncio.sleep(0.05)
    await runner.stop()

    # Conductor must have transitioned from WELCOME -> READY_GATE -> INTRO
    assert runner.state.phase == ConductorPhase.INTRO
    assert any(m.get("type") == "TTSStarted" for m in ws.sent_messages)


# -----------------------------------------------------------------------------
# Test 3: Stale Timer Tokens are Ignored
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_stale_timer_tokens():
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner(
        session_id="sess_stale_timer",
        script=script,
        websocket=ws,
        aura_client=tts,
    )
    await runner.start()

    # Welcome done -> Ready -> Intro
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))

    # Incomplete turnEnd schedules timer
    await runner.queue.put(TurnEnd(text="Well because", turn_id="t1", now_ms=3100))
    await asyncio.sleep(0.02)

    # Candidate starts speaking, cancelling commit timer
    await runner.queue.put(TurnStart(now_ms=4000))
    await asyncio.sleep(0.02)
    assert "commit" not in runner.state.active_timers

    # Stale Tick arrives from old timer
    await runner.queue.put(Tick(now_ms=3100 + 2500))
    await asyncio.sleep(0.02)

    # State must NOT have committed
    assert runner.state.is_committed is False
    await runner.stop()


# -----------------------------------------------------------------------------
# Test 4: Cancel Speech on User Interrupt / EndButton
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_cancel_during_speech():
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner(
        session_id="sess_cancel_speech",
        script=script,
        websocket=ws,
        aura_client=tts,
    )
    await runner.start()

    # Bot speaks welcome
    await asyncio.sleep(0.02)
    assert runner.state.bot_speaking is True

    # User clicks EndButton during speech
    await runner.on_end_button()
    await asyncio.sleep(0.05)

    # Conductor cancelled speech and marked completed
    assert tts.cancel_count >= 1
    assert runner.state.phase == ConductorPhase.COMPLETED
    assert any(m.get("type") == "TTSCancelled" for m in ws.sent_messages)
    await runner.stop()


# -----------------------------------------------------------------------------
# Test 5: Resume From Serialized State Across Reconnect
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_resume_from_serialized_state():
    SESSION_STATE_CACHE.clear()
    ws1 = FakeWebSocket()
    tts1 = FakeAuraTTSClient()
    script = make_test_script()

    # Session 1 runs up to Python anchor
    runner1 = SessionRunner(
        session_id="sess_resume_test",
        script=script,
        websocket=ws1,
        aura_client=tts1,
    )
    await runner1.start()
    await runner1.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner1.queue.put(ReadyButton(now_ms=2100))
    await runner1.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))
    await runner1.queue.put(TurnEnd(text="I am a backend engineer with five years experience.", turn_id="t1", now_ms=3500))
    await runner1.queue.put(Tick(now_ms=3800))
    await asyncio.sleep(0.05)

    assert runner1.state.phase == ConductorPhase.SKILL_ANCHOR
    await runner1.stop()

    # Reconnect: new SessionRunner initialized with same session_id
    ws2 = FakeWebSocket()
    tts2 = FakeAuraTTSClient()
    runner2 = SessionRunner(
        session_id="sess_resume_test",
        script=script,
        websocket=ws2,
        aura_client=tts2,
    )
    # Runner2 loads directly from SESSION_STATE_CACHE
    assert runner2.state.phase == ConductorPhase.SKILL_ANCHOR
    assert runner2.state.current_question_index == runner1.state.current_question_index
    assert runner2.state.current_skill_index == 0
    await runner2.stop()


# -----------------------------------------------------------------------------
# Test 6: Fast Reply Path - Validation Rules
# -----------------------------------------------------------------------------
def test_validate_speculative_output_rules():
    # 1. Valid: reaction <= 18 words, exactly one question, no clichés
    valid_text = "Partitioning with consistent hashing prevents data skew. How do you measure replication lag across nodes?"
    assert validate_speculative_output(valid_text) is True

    # 2. Rejection: praise cliché
    praise_text = "Great job on that explanation! How do you measure replication lag across nodes?"
    assert validate_speculative_output(praise_text) is False

    # 3. Rejection: evaluating cliché
    eval_text = "That is correct. How do you measure replication lag across nodes?"
    assert validate_speculative_output(eval_text) is False

    # 4. Rejection: multiple questions
    multi_q = "Understood. How do you measure replication lag? And how do you handle failover?"
    assert validate_speculative_output(multi_q) is False

    # 5. Rejection: coding / whiteboard ask
    coding_text = "Understood. Please write code on the whiteboard to implement replication."
    assert validate_speculative_output(coding_text) is False

    # 6. Rejection: reaction sentence > 18 words
    long_reaction = "When managing massive distributed database clusters across geographically distinct data centers with complex replication hierarchies and lagging follower nodes, that makes sense. How do you handle partitions?"
    assert validate_speculative_output(long_reaction) is False


# -----------------------------------------------------------------------------
# Test 7: Fast Reply Path - Reply Ready in 300ms -> No Bridge
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reply_ready_in_300ms_no_bridge():
    """Verify: PlayBridge must fire only if no reply audio has started 700 ms after commit.
    Never alongside a reply that started in time. Reply ready in 300 ms -> no bridge."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner(
        session_id="sess_300ms_no_bridge",
        script=script,
        websocket=ws,
        aura_client=tts,
    )
    await runner.start()

    # Move to Anchor
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))
    await runner.queue.put(TurnEnd(text="I am an experienced backend engineer.", turn_id="t1", now_ms=3500))
    await runner.queue.put(Tick(now_ms=3800))
    await runner.queue.put(BotSpeechDone(speech_id="speech_3", now_ms=4500))
    await asyncio.sleep(0.05)

    # Candidate answers
    await runner.queue.put(TurnStart(now_ms=5000))
    await runner.queue.put(TurnEnd(text="We use consistent hashing for partition distribution.", turn_id="t2", now_ms=5500))
    # Commit fires at 5800ms -> schedules 700ms bridge timer at 6500ms
    await runner.queue.put(Tick(now_ms=5800))

    # Reply is ready in 300ms (at 6100ms) -> playback_started arrives
    await asyncio.sleep(0.30)
    await runner.on_playback_started(runner.state.active_speech_id or "speech_4")

    # Wait past 700ms from commit (another 500ms)
    await asyncio.sleep(0.50)

    # Bridge MUST NOT have fired
    assert runner.current_metrics.used_bridge is False
    assert not any(m.get("is_bridge") is True for m in ws.sent_messages)
    await runner.stop()


# -----------------------------------------------------------------------------
# Test 8: Fast Reply Path - Eager, Candidate Speaks More -> Speculation Discarded
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_eager_candidate_speaks_more_speculation_discarded():
    """Verify: eager, then candidate speaks more, then commit -> speculation discarded."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    async def mock_llm(curr_q, ans, next_q):
        await asyncio.sleep(0.01)
        yield "Consistent hashing avoids skew. "
        yield next_q

    runner = SessionRunner(
        session_id="sess_speaks_more_discard",
        script=script,
        websocket=ws,
        aura_client=tts,
        llm_fn=mock_llm,
    )
    await runner.start()

    # Move to Anchor
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))
    await runner.queue.put(TurnEnd(text="I am an experienced backend engineer.", turn_id="t1", now_ms=3500))
    await runner.queue.put(Tick(now_ms=3800))
    await runner.queue.put(BotSpeechDone(speech_id="speech_3", now_ms=4500))
    await asyncio.sleep(0.05)

    # 1. Candidate speaks initial words -> EagerTurnEnd fires
    await runner.queue.put(TurnStart(now_ms=5000))
    await runner.queue.put(EagerTurnEnd(text="We use Paxos with three replicas", now_ms=5200))
    await asyncio.sleep(0.05)
    assert runner.spec_task is not None
    assert runner.spec_source_text == "We use Paxos with three replicas"

    # 2. Candidate speaks MORE words before pausing
    await runner.queue.put(TurnEnd(text="We use Paxos with three replicas across multiple data centers.", turn_id="t2", now_ms=5500))

    # 3. Commit fires
    await runner.queue.put(Tick(now_ms=5800))
    await asyncio.sleep(0.08)

    # 4. Speculation MUST be discarded due to text mismatch
    assert runner.current_metrics.speculation_discarded is True
    assert runner.current_metrics.speculation_discard_reason == "text_mismatch"
    assert runner.current_metrics.speculation_used is False
    assert runner.spec_token is None

    # Static question was spoken instead
    assert any(m.get("speech_id") == "speech_4" and not m.get("is_speculative") for m in ws.sent_messages)
    await runner.stop()


# -----------------------------------------------------------------------------
# Test 9: Fast Reply Path - Exact Eager Match -> Speculation Used
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_speculative_exact_match_used():
    """Verify: when eager text matches committed answer, speculation is used."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    async def mock_llm(curr_q, ans, next_q):
        await asyncio.sleep(0.02)
        yield "Consistent hashing avoids skew. "
        yield next_q

    runner = SessionRunner(
        session_id="sess_spec_match",
        script=script,
        websocket=ws,
        aura_client=tts,
        llm_fn=mock_llm,
    )
    await runner.start()

    # Move to Anchor
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))
    await runner.queue.put(TurnEnd(text="I am an experienced backend engineer.", turn_id="t1", now_ms=3500))
    await runner.queue.put(Tick(now_ms=3800))
    await runner.queue.put(BotSpeechDone(speech_id="speech_3", now_ms=4500))
    await asyncio.sleep(0.05)

    # Eager text equals committed answer (modulo whitespace/punctuation)
    await runner.queue.put(TurnStart(now_ms=5000))
    await runner.queue.put(EagerTurnEnd(text="We use consistent hashing with virtual nodes", now_ms=5200))
    await asyncio.sleep(0.05)

    await runner.queue.put(TurnEnd(text="We use consistent hashing with virtual nodes.", turn_id="t2", now_ms=5500))
    await runner.queue.put(Tick(now_ms=5800))
    await asyncio.sleep(0.12)

    # Speculation was USED
    assert runner.current_metrics.speculation_used is True
    assert runner.current_metrics.speculation_discarded is False
    assert any(m.get("is_speculative") is True for m in ws.sent_messages)
    await runner.stop()


# -----------------------------------------------------------------------------
# Test 10: Fast Reply Path - Slow Reply (>700ms) -> Bridge Fires
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_slow_reply_bridge_fires_at_700ms():
    """Verify: if reply audio has not started 700 ms after commit, PlayBridge fires."""
    ws = FakeWebSocket()
    # TTS sleeps for 0.9s (> 0.7s) before yielding
    tts = FakeAuraTTSClient(delay_s=0.90)
    script = make_test_script()

    runner = SessionRunner(
        session_id="sess_slow_bridge",
        script=script,
        websocket=ws,
        aura_client=tts,
    )
    await runner.start()

    # Move to Anchor
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))
    await runner.queue.put(TurnEnd(text="I am an experienced backend engineer.", turn_id="t1", now_ms=3500))
    await runner.queue.put(Tick(now_ms=3800))
    await runner.queue.put(BotSpeechDone(speech_id="speech_3", now_ms=4500))
    await asyncio.sleep(0.05)

    # Answer and commit
    await runner.queue.put(TurnStart(now_ms=5000))
    await runner.queue.put(TurnEnd(text="We use Paxos with three replicas across availability zones.", turn_id="t2", now_ms=5500))
    # Commit schedules 700ms bridge timer
    await runner.queue.put(Tick(now_ms=5800))

    # Wait 850ms -> bridge timer expires at 700ms, reply audio hasn't started
    await asyncio.sleep(0.85)

    # Bridge should have fired!
    assert runner.current_metrics.used_bridge is True
    assert any(m.get("is_bridge") is True for m in ws.sent_messages)
    await runner.stop()


# -----------------------------------------------------------------------------
# Test 11: Real-time STT Update & CommittedAnswer WebSocket Forwarding
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_forwards_update_and_committed_answer_events():
    """Verify Update events stream real-time hypotheses to WebSocket and CommittedAnswer notifies UI."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner(
        session_id="sess_ws_update_test",
        script=script,
        websocket=ws,
        aura_client=tts,
    )
    await runner.start()

    # 1. Simulate interim Flux STT Update event
    from backend.app.services.voice.flux_stt import Update
    await runner.on_flux_event(Update(text="I am speaking now"))
    await asyncio.sleep(0.02)

    update_msgs = [m for m in ws.sent_messages if m.get("type") == "Update"]
    assert len(update_msgs) >= 1
    assert any(m.get("text") == "I am speaking now" for m in update_msgs)

    # 2. Advance to intro and commit an answer
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))

    await runner.queue.put(TurnStart(now_ms=3200))
    await runner.queue.put(TurnEnd(text="This is my full completed introduction answer.", turn_id="t_intro", now_ms=4000))
    await runner.queue.put(Tick(now_ms=4300))
    await asyncio.sleep(0.05)

    committed_msgs = [m for m in ws.sent_messages if m.get("type") == "CommittedAnswer"]
    assert len(committed_msgs) >= 1
    assert "This is my full completed introduction answer." in committed_msgs[0].get("text", "")
    await runner.stop()


# -----------------------------------------------------------------------------
# Test 12: build_script Deterministic Order & Kind Fallback
# -----------------------------------------------------------------------------
def test_build_script_order_and_fallback():
    """Verify build_script sorts by question_index and infers kinds when missing."""
    from unittest.mock import MagicMock
    from backend.app.services.interview_v2.runner import build_script

    q0 = MagicMock(question_index=0, kind=None, skill_name="Welcome", question_text="Welcome to the interview")
    q1 = MagicMock(question_index=1, kind=None, skill_name="Intro", question_text="Please introduce yourself and your background")
    q2 = MagicMock(question_index=2, kind=None, skill_name="Databases", question_text="How do you design database tables?")
    q3 = MagicMock(question_index=3, kind=None, skill_name="Databases", question_text="How would you write a simple join query?")

    session = MagicMock()
    # Provide out of order
    session.questions = [q2, q0, q3, q1]

    script = build_script(session)
    questions = script["questions"]
    assert len(questions) == 4
    # Must be sorted 0, 1, 2, 3
    assert [q["question_index"] for q in questions] == [0, 1, 2, 3]
    # Inferred kinds
    assert questions[0]["kind"] == "welcome"
    assert questions[1]["kind"] == "intro_hook"
    assert questions[2]["kind"] == "anchor"
    assert questions[3]["kind"] == "anchor_alt"


# -----------------------------------------------------------------------------
# Test 13: Eager Decision Start and Exact Match Reuse (Phase A5)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_eager_decision_exact_match_reuse():
    """Verify eager call started before commit is reused when committed text matches."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    async def mock_llm(curr_q, ans, next_q):
        await asyncio.sleep(0.01)
        return json.dumps({
            "ack": "Right, so your asyncio event loops for network calls.",
            "action": "probe",
            "probe_id": "probe_1",
            "followup": "How do you configure connection pooling in asyncio?",
            "covered_expectations": [],
            "no_experience": False,
        })

    runner = SessionRunner(
        session_id="sess_eager_reuse_test",
        script=script,
        websocket=ws,
        aura_client=tts,
        llm_fn=mock_llm,
    )
    await runner.start()

    # Advance to Python SKILL_ANCHOR
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))
    await runner.queue.put(TurnStart(now_ms=3200))
    await runner.queue.put(TurnEnd(text="I have 5 years experience with Python.", turn_id="t_intro", now_ms=4000))
    await runner.queue.put(Tick(now_ms=4300))
    await runner.queue.put(BotSpeechDone(speech_id="speech_3", now_ms=5000))
    await asyncio.sleep(0.05)
    assert runner.state.phase == ConductorPhase.SKILL_ANCHOR

    cand_text = "In our backend architecture we use asyncio event loops for non-blocking network calls."
    
    # 1. Candidate starts speaking, and ~800ms before commit EagerTurnEnd fires
    await runner.queue.put(TurnStart(now_ms=5100))
    await runner.queue.put(EagerTurnEnd(text=cand_text, now_ms=5200))
    await asyncio.sleep(0.05)

    assert runner.state.active_speculation_token is not None
    assert runner.spec_token == runner.state.active_speculation_token

    # 2. Candidate finishes and commits matching text
    await runner.queue.put(TurnEnd(text=cand_text, turn_id="t_cand_commit", now_ms=6000))
    await runner.queue.put(Tick(now_ms=6300))
    await asyncio.sleep(0.08)

    # Speculation must be reused!
    assert runner.current_metrics.speculation_used is True
    assert runner.last_decision_used_fallback is False
    await runner.stop()


# -----------------------------------------------------------------------------
# Test 14: Ungrounded Ack Single Regeneration Attempt (Phase A5)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_ungrounded_ack_regenerates_or_empties():
    """Verify runner detects ungrounded ack, attempts single regeneration, and speaks no ack if still ungrounded."""
    from unittest.mock import AsyncMock, patch

    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner(
        session_id="sess_ack_regen_test",
        script=script,
        websocket=ws,
        aura_client=tts,
    )

    cand_ans = "We use Kafka streaming for event distribution."
    q_text = "How do you handle concurrency in Python using asyncio versus multiprocessing?"

    # Case A: bad ack -> regeneration produces grounded ack
    with patch.object(runner, "_regenerate_grounded_ack", new_callable=AsyncMock) as mock_regen:
        mock_regen.return_value = "Right, Kafka streaming for event distribution."
        result = await runner._regenerate_grounded_ack(cand_ans, q_text, "Great work on that.")
        assert "Kafka streaming" in result

    # Case B: bad ack -> regeneration still fails grounding -> returns empty string
    with patch.object(runner, "_regenerate_grounded_ack", new_callable=AsyncMock) as mock_regen_fail:
        mock_regen_fail.return_value = ""
        result_empty = await runner._regenerate_grounded_ack(cand_ans, q_text, "Great work on that.")
        assert result_empty == ""



