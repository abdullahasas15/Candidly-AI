"""Verification test suite proving all 9 verified failure mode fixes for Director v2.

Covers:
1. Live Decision Path (runner._call_decision_llm without NameError, consistent on_stream_ack)
2. Canonical Decision Contract (off_topic, legacy mappings, round-trip model validation)
3. Conductor Pacing Loops (all core expectations covered & followups_used >= 2 advance skill)
4. Intro Fallbacks & Speculation (context-aware fallback, intro speculation snapshot matches committed)
5. Agenda Behavior (negative reply silence fallback, negation parsing, happy path)
6. Health Check & Fast Ack (missing token sets DIRECTOR_MODEL_AVAILABLE=False, router startup)
7. Audio & SpeakAck Sequence (TTSStarted, binary audio, TTSDone, BotSpeechDone)
8. Real Runner DB Persistence (dynamic question creation and coverage saved to candidly_test)
9. Full Interview Progression (Greeting -> Agenda -> Intro -> 2 Skills -> Close)
"""

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.models import User, JobPosting, JobApplication, InterviewSession
from backend.app.services.llm_router import get_bedrock_bearer_token
from backend.app.services.interview_v2.conductor import (
    ConductorState,
    ConductorPhase,
    SessionStart,
    TurnStart,
    TurnEnd,
    EagerTurnEnd,
    BotSpeechDone,
    BotAudioStarted,
    Tick,
    ReadyButton,
    CommitButton,
    Speak,
    SpeakAck,
    RequestDecision,
    AckReady,
    DecisionReady,
    ScheduleTimer,
    CancelTimer,
    PlayBridge,
    EmitUI,
    step,
    validate_and_apply_decision,
    classify_greeting_reply,
    extract_prioritized_skill,
)
from backend.app.services.interview_v2 import director
from backend.app.services.interview_v2.director import (
    DirectorDecision,
    generate_director_decision,
    verify_director_model,
)
from backend.app.services.interview_v2.runner import SessionRunner
from tests.test_runner_v2 import FakeWebSocket, FakeAuraTTSClient, make_test_script


def make_test_plan():
    return {
        "questions": [
            {
                "question_index": 0,
                "kind": "welcome",
                "skill_name": "Welcome & Agenda",
                "question_text": "Hi! Welcome. We will cover Python and Distributed Systems. Ready?",
                "priority_tier": "P0",
            },
            {
                "question_index": 1,
                "kind": "intro_hook",
                "skill_name": "Introduction",
                "question_text": "Could you introduce yourself and tell us about your recent work?",
                "priority_tier": "P0",
            },
            {
                "question_index": 2,
                "kind": "anchor",
                "skill_name": "Python",
                "question_text": "How do you handle concurrency in Python using asyncio versus multiprocessing?",
                "expected_key_points": ["asyncio", "multiprocessing"],
                "priority_tier": "P0",
            },
            {
                "question_index": 3,
                "kind": "anchor",
                "skill_name": "Distributed Systems",
                "question_text": "How do you design a reliable retry mechanism using backoff?",
                "expected_key_points": ["exponential backoff", "jitter"],
                "priority_tier": "P0",
            },
            {
                "question_index": 888,
                "kind": "candidate_qa",
                "skill_name": "Candidate Q&A",
                "question_text": "Do you have any questions for us?",
                "priority_tier": "P0",
            },
        ],
    }


# =============================================================================
# Fix 1: Live Decision Path (runner._call_decision_llm without NameError)
# =============================================================================
@pytest.mark.asyncio
async def test_fix_1_live_decision_path_no_name_error_director():
    """_call_decision_llm with llm_fn=None invokes Director cleanly without NameError."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner("sess_live_dir_call", script, ws, tts, llm_fn=None)
    await runner.start()
    await asyncio.sleep(0.02)

    req = RequestDecision(
        token="tok_dir_1",
        skill="Python",
        question_text="How do you handle concurrency in Python using asyncio versus multiprocessing?",
        answer_text="I use asyncio event loops for network I/O.",
    )

    mock_decision = DirectorDecision(
        action="follow_up",
        ack="Right, asyncio handles high concurrent I/O.",
        transition="Let's build on that.",
        question="How do you handle unhandled exceptions in background tasks?",
        target_skill="Python",
        covered_expectation_ids=["asyncio"],
    )

    with patch(
        "backend.app.services.interview_v2.runner.generate_director_decision",
        new_callable=AsyncMock,
        return_value=(mock_decision, {"ttft_ms": 120, "model_name": "nova-pro", "provider": "bedrock"}),
    ) as mock_gen:
        # Call the actual live decision method
        await runner._call_decision_llm(req)

        assert mock_gen.called
        call_kwargs = mock_gen.call_args.kwargs
        assert "on_ack_ready" in call_kwargs
        assert callable(call_kwargs["on_ack_ready"])

        # Collect events from runner queue until DecisionReady is received
        decision_event = None
        for _ in range(5):
            ev = await asyncio.wait_for(runner.queue.get(), timeout=1.0)
            if isinstance(ev, DecisionReady):
                decision_event = ev
                break
        assert decision_event is not None
        assert decision_event.decision is not None
        assert decision_event.decision["action"] == "follow_up"
        assert decision_event.decision["question"] == "How do you handle unhandled exceptions in background tasks?"

    await runner.stop()


@pytest.mark.asyncio
async def test_fix_1_live_decision_path_no_name_error_candidate_qa():
    """_call_decision_llm with llm_fn=None handles Candidate Q&A without NameError."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner("sess_live_qa_call", script, ws, tts, llm_fn=None)
    await runner.start()
    await asyncio.sleep(0.02)

    req = RequestDecision(
        token="tok_qa_1",
        skill="Candidate Q&A",
        question_text="Do you have any questions for us?",
        answer_text="What does a typical day look like for the engineering team?",
    )

    qa_return = {
        "action": "candidate_qa",
        "ack": "Great question about daily workflow.",
        "transition": "",
        "question": "Does that give you a good picture, or would you like to know more?",
    }

    with patch(
        "backend.app.services.interview_v2.runner.stream_decision_with_ack_first",
        new_callable=AsyncMock,
        return_value=(qa_return, {"ttft_ms": 100}),
    ) as mock_qa:
        await runner._call_decision_llm(req)

        assert mock_qa.called
        call_kwargs = mock_qa.call_args.kwargs
        assert "on_ack_ready" in call_kwargs
        assert callable(call_kwargs["on_ack_ready"])

        decision_event = None
        for _ in range(5):
            ev = await asyncio.wait_for(runner.queue.get(), timeout=1.0)
            if isinstance(ev, DecisionReady):
                decision_event = ev
                break
        assert decision_event is not None
        assert decision_event.decision is not None
        assert decision_event.decision["action"] == "candidate_qa"

    await runner.stop()


# =============================================================================
# Fix 2: Canonical Decision Contract (off_topic & legacy action mapping)
# =============================================================================
def test_fix_2_canonical_contract_accepts_off_topic_and_all_canonical_actions():
    """DirectorDecision accepts off_topic and all canonical actions."""
    canonical_actions = [
        "follow_up",
        "new_topic",
        "clarify",
        "off_topic",
        "rephrase",
        "candidate_qa",
        "close",
    ]
    for act in canonical_actions:
        dec = DirectorDecision.model_validate({
            "action": act,
            "question": f"Question for {act}",
            "ack": f"Ack for {act}",
        })
        assert dec.action == act


def test_fix_2_legacy_action_and_field_mapping_before_validation():
    """Legacy actions and fields are mapped before model validation."""
    legacy_cases = [
        ({"action": "probe", "followup": "Can you explain?"}, "follow_up", "Can you explain?"),
        ({"action": "escalate", "followup": "What about edge cases?"}, "follow_up", "What about edge cases?"),
        ({"action": "hypothetical", "followup": "Imagine a scale of 10M?"}, "follow_up", "Imagine a scale of 10M?"),
        ({"action": "next", "question": "Let's move on."}, "new_topic", "Let's move on."),
        ({"action": "alt", "question": "Could you clarify?"}, "clarify", "Could you clarify?"),
        ({"action": "qa_reply", "question": "Any other questions?"}, "candidate_qa", "Any other questions?"),
    ]
    for raw_data, expected_action, expected_question in legacy_cases:
        dec = DirectorDecision.model_validate(raw_data)
        assert dec.action == expected_action
        assert dec.question == expected_question

    # Field mapping: covered_expectations -> covered_expectation_ids
    dec = DirectorDecision.model_validate({
        "action": "follow_up",
        "covered_expectations": ["exp_1", "exp_2"],
    })
    assert dec.covered_expectation_ids == ["exp_1", "exp_2"]


@pytest.mark.asyncio
async def test_fix_2_round_trip_through_generate_director_decision():
    """DirectorDecision round-trips cleanly through generate_director_decision."""
    llm_output = {
        "action": "off_topic",
        "ack": "I hear you.",
        "transition": "Let's return to the topic.",
        "question": "How do you handle Python concurrency?",
        "target_skill": "Python",
        "target_expectation_ids": [],
        "covered_expectation_ids": [],
    }

    async def mock_llm_fn(sys_prompt, usr_prompt):
        return json.dumps(llm_output)

    director_context = {
        "current_question": "How do you handle concurrency?",
        "candidate_answer": "I like sports.",
        "current_skill": "Python",
        "available_competencies": [
            {"name": "Python", "weight": 1.0, "anchor_question": "How do you handle concurrency?", "expected_key_points": ["asyncio"]},
        ],
        "remaining_topics": [],
        "asked_questions": ["How do you handle concurrency?"],
        "recent_turns": [],
        "topic_summaries": {},
        "coverage": {},
        "unresolved_threads": [],
        "followups_used_in_topic": 0,
        "time_left_ms": 300000,
    }

    dec, metrics = await generate_director_decision(
        context=director_context,
        mock_llm_fn=mock_llm_fn,
    )
    assert isinstance(dec, DirectorDecision)
    assert dec.action == "off_topic"
    assert dec.question == "How do you handle Python concurrency?"
    assert dec.ack == "I hear you."


# =============================================================================
# Fix 3: Conductor Pacing Loops (Advance to Different Skill)
# =============================================================================
def test_fix_3_conductor_pacing_loops_all_core_covered():
    """When all core expectations are covered, conductor advances to a different uncompleted skill."""
    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="test_pacing_cov", plan=make_test_plan(), now_ms=1000))
    state.phase = ConductorPhase.SKILL_ANCHOR
    state.current_skill_index = 0
    state.current_question_index = 2
    curr_skill = state.skill_names[state.current_skill_index]
    assert curr_skill == "Python"

    state.committed_answer = "I use asyncio for cooperative multitasking and multiprocessing for CPU."
    state.awaiting_decision = True
    state.decision_token = "dec_cov_1"

    decision = {
        "action": "follow_up",
        "ack": "Spot on explanation of both.",
        "transition": "Moving forward.",
        "question": "Can you explain event loop internals?",
        "target_skill": "Python",
        "covered_expectation_ids": ["asyncio", "multiprocessing"],  # covers all!
    }

    new_state, effects = validate_and_apply_decision(state, decision, now_ms=5000)

    # Conductor must advance to a DIFFERENT skill and not re-ask Python anchor
    assert new_state.phase == ConductorPhase.SKILL_ANCHOR
    assert new_state.current_skill_index == 1
    new_skill = new_state.skill_names[new_state.current_skill_index]
    assert new_skill != "Python"
    assert new_skill == "Distributed Systems"

    speak = next(e for e in effects if isinstance(e, Speak))
    assert "retry mechanism" in speak.text
    assert "concurrency in Python" not in speak.text


def test_fix_3_conductor_pacing_loops_max_followups():
    """When followups_used >= 2, conductor forces new_topic and advances to next skill."""
    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="test_pacing_max", plan=make_test_plan(), now_ms=1000))
    state.phase = ConductorPhase.SKILL_FOLLOWUP
    state.current_skill_index = 0
    state.current_question_index = 2
    state.followups_used = 2  # Already used 2 followups on Python!

    state.committed_answer = "We also tune uvloop settings."
    state.awaiting_decision = True
    state.decision_token = "dec_max_1"

    # Director tries to ask yet another follow-up on Python
    decision = {
        "action": "follow_up",
        "ack": "Got it.",
        "question": "What about Python GIL?",
        "target_skill": "Python",
        "covered_expectation_ids": [],
    }

    new_state, effects = validate_and_apply_decision(state, decision, now_ms=6000)

    # Must transition to Distributed Systems
    assert new_state.phase == ConductorPhase.SKILL_ANCHOR
    assert new_state.current_skill_index == 1
    assert new_state.skill_names[new_state.current_skill_index] == "Distributed Systems"
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "retry mechanism" in speak.text


# =============================================================================
# Fix 4: Intro Fallbacks & Speculation Snapshot Alignment
# =============================================================================
def test_fix_4_intro_fallback_context_aware_and_degraded_flag():
    """Null or invalid intro decision uses context-aware fallback and marks degraded_intro."""
    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="test_intro_fb", plan=make_test_plan(), now_ms=1000))
    state.phase = ConductorPhase.INTRO
    state.current_question_index = 1
    state.awaiting_decision = True
    state.decision_token = "dec_intro_fb"

    # Candidate explicitly talked about Distributed Systems in their intro
    state.committed_answer = "I specialize in distributed systems architecture and fault tolerance."

    new_state, effects = validate_and_apply_decision(state, None, now_ms=4000)

    # 1. Marked as degraded_intro in director_memory
    assert new_state.director_memory.get("degraded_intro") is True
    # 2. Context-aware fallback chose Distributed Systems based on answer text!
    assert new_state.phase == ConductorPhase.SKILL_ANCHOR
    assert new_state.skill_names[new_state.current_skill_index] == "Distributed Systems"
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "retry mechanism" in speak.text


@pytest.mark.asyncio
async def test_fix_4_intro_speculation_matches_committed_snapshot():
    """Intro speculation snapshot uses curr_skill='Introduction' matching committed turn."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    async def mock_llm(curr_q, ans, next_q):
        return json.dumps({
            "action": "new_topic",
            "ack": "Thanks for sharing.",
            "question": "How do you handle distributed partition replication?",
            "target_skill": "Distributed Storage",
            "covered_expectation_ids": [],
        })

    runner = SessionRunner("sess_spec_intro_match", script, ws, tts, llm_fn=mock_llm)
    await runner.start()

    # Move through Welcome -> ReadyGate -> Intro
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await runner.queue.put(ReadyButton(now_ms=2100))
    await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))
    await asyncio.sleep(0.02)
    assert runner.state.phase == ConductorPhase.INTRO

    # Candidate speaks intro -> EagerTurnEnd fires
    await runner.queue.put(TurnStart(now_ms=3200))
    await runner.queue.put(
        EagerTurnEnd(
            text="I am a distributed systems engineer with 5 years experience.",
            now_ms=3400,
        )
    )
    await asyncio.sleep(0.05)

    assert runner.spec_task is not None
    assert runner.spec_snapshot is not None
    # CRITICAL: Speculation snapshot must be Introduction, NOT Python!
    assert runner.spec_snapshot.skill_name == "Introduction"

    await runner.stop()


# =============================================================================
# Fix 5: Agenda Behavior (Negative Reply Silence, Negation Parsing, Happy Path)
# =============================================================================
def test_fix_5_agenda_negative_followed_by_silence():
    """Negative agenda reply followed by silence timeout does not say 'take that as a yes'."""
    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="test_agenda_neg_sil", plan=make_test_plan(), now_ms=1000))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, TurnEnd(text="Ready.", turn_id="g1", now_ms=2500))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    assert state.phase == ConductorPhase.AGENDA_RESPONSE

    # Candidate says negative reply without specifying topic
    state, effects1 = step(state, TurnEnd(text="Actually, could we adjust the agenda?", turn_id="a1", now_ms=3500))
    assert state.agenda_adjustments == 1
    assert state.phase == ConductorPhase.AGENDA_RESPONSE
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=4500))

    # Candidate stays silent until agenda_silence timeout expires
    state, effects2 = step(state, Tick(now_ms=9000))
    assert state.phase == ConductorPhase.INTRO
    speak = next(e for e in effects2 if isinstance(e, Speak))
    # Must NOT say "take that as a yes"
    assert "take that as a yes" not in speak.text.lower()
    assert "keep the current agenda and adapt as we go" in speak.text.lower()


def test_fix_5_agenda_negation_parsing():
    """extract_prioritized_skill prioritizes the intended topic over negated topic."""
    skill_names = ["Python", "Distributed Systems"]
    text = "I don't want Python, distributed systems is better"
    prioritized = extract_prioritized_skill(text, skill_names)
    assert prioritized == "Distributed Systems"


def test_fix_5_agenda_happy_path():
    """Candidate agrees to agenda -> cleanly transitions to INTRO."""
    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="test_agenda_happy", plan=make_test_plan(), now_ms=1000))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, TurnEnd(text="Ready.", turn_id="g1", now_ms=2500))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    assert state.phase == ConductorPhase.AGENDA_RESPONSE

    state, effects = step(state, TurnEnd(text="Sounds great, let's do it!", turn_id="a1", now_ms=3500))
    assert state.phase == ConductorPhase.INTRO
    speak = next(e for e in effects if isinstance(e, Speak))
    assert "introduce yourself" in speak.text.lower()


# =============================================================================
# Fix 6: Health Check & Fast Ack
# =============================================================================
def test_fix_6_health_check_missing_token_sets_unavailable():
    """verify_director_model sets DIRECTOR_MODEL_AVAILABLE=False when token is missing."""
    director.DIRECTOR_MODEL_AVAILABLE = True
    with patch("backend.app.services.interview_v2.director.get_bedrock_bearer_token", return_value=None), \
         patch.dict(os.environ, {"FORCE_HEALTH_CHECK": "1"}):
        result = verify_director_model()
        assert result is False
        assert director.DIRECTOR_MODEL_AVAILABLE is False


@pytest.mark.asyncio
async def test_fix_6_router_startup_invokes_verify_director_model():
    """Router startup verifies director model health."""
    from backend.app.services.interview_v2.router import _on_startup

    with patch("backend.app.services.interview_v2.director.verify_director_model", return_value=True) as mock_verify:
        await _on_startup()
        assert mock_verify.called


# =============================================================================
# Fix 7: Audio & SpeakAck Full Sequence
# =============================================================================
@pytest.mark.asyncio
async def test_fix_7_speak_ack_full_sequence_through_runner():
    """SpeakAck executes through SessionRunner: TTSStarted, BotSpeechStarted, audio, TTSDone, BotSpeechDone."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner("sess_speak_ack_seq", script, ws, tts)
    await runner.start()
    await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
    await asyncio.sleep(0.02)
    runner.state.active_timers.clear()

    ack_speech_id = "ack_speech_sequence_1"
    runner.state.active_speech_id = ack_speech_id
    speak_ack_effect = SpeakAck(
        token="dec_token_seq_1",
        text="Right, asyncio handles non-blocking sockets.",
        speech_id=ack_speech_id,
        action="follow_up",
    )

    await runner._execute_effect(speak_ack_effect)
    if runner.speech_task:
        await runner.speech_task
    await asyncio.sleep(0.05)

    # 1. TTSStarted sent over WebSocket with is_ack=True
    tts_started = next((m for m in ws.sent_messages if m.get("type") == "TTSStarted" and m.get("is_ack")), None)
    assert tts_started is not None
    assert tts_started["speech_id"] == ack_speech_id
    assert tts_started["is_ack"] is True

    # 2. Binary audio frames were sent over WebSocket
    assert len(ws.sent_bytes) > 0

    # 3. TTSDone sent over WebSocket
    tts_done = next((m for m in ws.sent_messages if m.get("type") == "TTSDone" and m.get("speech_id") == ack_speech_id), None)
    assert tts_done is not None
    assert tts_done["speech_id"] == ack_speech_id

    # 4. BotSpeechDone processed by conductor -> ack_playback_ended_at_ms recorded
    assert runner.state.ack_playback_ended_at_ms is not None

    await runner.stop()


# =============================================================================
# Fix 8: Real Runner DB Persistence (candidly_test)
# =============================================================================
@pytest.mark.asyncio
async def test_fix_8_director_real_runner_db_persistence():
    """SessionRunner persists dynamic questions and coverage updates to candidly_test DB."""
    now_ts = int(asyncio.get_running_loop().time() * 1000)
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"recruiter_test_{now_ts}@example.com",
            full_name="Recruiter Test",
            role="recruiter",
            password_hash="pw",
        )
        candidate = User(
            email=f"candidate_test_{now_ts}@example.com",
            full_name="Alex Test",
            role="candidate",
            password_hash="pw",
        )
        db.add_all([recruiter, candidate])
        await db.flush()

        job = JobPosting(
            job_title="Distributed Systems Engineer",
            department="Engineering",
            recruiter_id=recruiter.id,
            status="active",
        )
        db.add(job)
        await db.flush()

        app_record = JobApplication(
            job_id=job.id,
            candidate_id=candidate.id,
            full_name=candidate.full_name,
            email=candidate.email,
            status="interview_ready",
        )
        db.add(app_record)
        await db.flush()

        session = InterviewSession(
            application_id=app_record.id,
            job_id=job.id,
            status="in_progress",
            current_phase="interview",
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner(session_id, script, ws, tts, llm_fn=None)
    await runner.start()

    mock_decision = DirectorDecision(
        action="follow_up",
        ack="Right, Paxos handles distributed consensus.",
        transition="Let's dive into compaction.",
        question="How do you handle log compaction in Paxos?",
        target_skill="Distributed Storage",
        covered_expectation_ids=["replication"],
    )

    with patch(
        "backend.app.services.interview_v2.runner.generate_director_decision",
        new_callable=AsyncMock,
        return_value=(mock_decision, {"ttft_ms": 100}),
    ):
        # Progress Welcome -> ReadyGate -> Intro
        await runner.queue.put(BotSpeechDone(speech_id="speech_1", now_ms=2000))
        await runner.queue.put(ReadyButton(now_ms=2100))
        await runner.queue.put(BotSpeechDone(speech_id="speech_2", now_ms=3000))
        await asyncio.sleep(0.02)
        assert runner.state.phase == ConductorPhase.INTRO

        # Candidate intro
        await runner.queue.put(TurnStart(now_ms=3200))
        await runner.queue.put(TurnEnd(text="I build distributed storage systems.", turn_id="t_intro", now_ms=3500))
        await runner.queue.put(CommitButton(now_ms=3600))

        # Wait for intro decision to transition to SKILL_ANCHOR
        deadline = asyncio.get_running_loop().time() + 2.0
        while runner.state.phase != ConductorPhase.SKILL_ANCHOR and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
        assert runner.state.phase == ConductorPhase.SKILL_ANCHOR

        # Bot speaks anchor question
        await runner.queue.put(BotSpeechDone(speech_id=runner.state.active_speech_id or "speech_3", now_ms=4500))
        await asyncio.sleep(0.02)

        # Candidate answers anchor question
        await runner.queue.put(TurnStart(now_ms=5000))
        await runner.queue.put(TurnEnd(text="We use Paxos with replication across three availability zones.", turn_id="t_anchor", now_ms=5500))
        await runner.queue.put(CommitButton(now_ms=5600))

        # Wait for follow_up decision
        deadline = asyncio.get_running_loop().time() + 2.0
        while runner.state.phase != ConductorPhase.SKILL_FOLLOWUP and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)

    assert runner.state.phase == ConductorPhase.SKILL_FOLLOWUP

    # Let the runner finish dispatching effects/checkpoints for this event before
    # taking the authoritative snapshot. This removes the race where a state read
    # could occur mid-event while the follow-up decision is still being applied.
    drain_deadline = asyncio.get_running_loop().time() + 1.0
    while not runner.queue.empty() and asyncio.get_running_loop().time() < drain_deadline:
        await asyncio.sleep(0.01)
    await runner._flush_checkpoint_chain()

    # The in-memory state must already reflect the decision coverage before persistence.
    assert "replication" in runner.state.covered_expectations_per_skill.get("Distributed Storage", []), (
        f"coverage={runner.state.covered_expectations_per_skill} "
        f"phase={runner.state.phase} before_commit={runner.state.phase_before_commit} "
        f"decision={runner.last_raw_decision}"
    )

    # Commit state to DB via runner persistence
    await runner._save_state(force_db=True)
    await runner._flush_checkpoint_chain()

    # Verify directly from DB
    async with AsyncSessionLocal() as verify_db:
        result = await verify_db.execute(
            select(InterviewSession).where(InterviewSession.id == session_id)
        )
        saved_session = result.scalar_one_or_none()
        assert saved_session is not None
        assert saved_session.runtime_state is not None
        runtime_dict = saved_session.runtime_state.get("conductor_v2", saved_session.runtime_state)

        # Dynamic question was registered in questions list in DB!
        questions = runtime_dict.get("questions", [])
        dyn_q = next((q for q in questions if q.get("kind") == "director_question"), None)
        assert dyn_q is not None
        assert "log compaction in Paxos" in dyn_q.get("question_text")

        # Covered expectations saved in DB!
        covered = runtime_dict.get("covered_expectations_per_skill", {})
        assert "replication" in covered.get("Distributed Storage", [])

    await runner.stop()


# =============================================================================
# Fix 9: E2E Full Interview Progression
# =============================================================================
def test_fix_9_e2e_full_interview_progression():
    """Verify clean hands-free progression: Greeting -> Agenda -> Intro -> 2 Skills -> Close."""
    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="test_e2e_full", plan=make_test_plan(), now_ms=1000))
    assert state.phase == ConductorPhase.GREETING

    # 1. Greeting response
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    assert state.phase == ConductorPhase.GREETING_RESPONSE
    state, _ = step(state, TurnEnd(text="Hi, I'm ready to interview.", turn_id="g", now_ms=2500))
    assert state.phase == ConductorPhase.AGENDA

    # 2. Agenda response
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    assert state.phase == ConductorPhase.AGENDA_RESPONSE
    state, _ = step(state, TurnEnd(text="The agenda looks good to me.", turn_id="a", now_ms=3500))
    assert state.phase == ConductorPhase.INTRO

    # 3. Intro response
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=4000))
    state, _ = step(state, TurnEnd(text="I have 5 years building scalable Python services.", turn_id="t_intro", now_ms=4500))
    state, effects = step(state, CommitButton(now_ms=4600))
    intro_req = next(e for e in effects if isinstance(e, RequestDecision))

    # Director selects Python
    state, _ = step(
        state,
        DecisionReady(
            token=intro_req.token,
            decision={
                "action": "new_topic",
                "ack": "Thanks for sharing your background.",
                "target_skill": "Python",
                "question": "How do you manage asyncio concurrency in production?",
            },
            now_ms=4900,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.skill_names[state.current_skill_index] == "Python"

    # 4. Skill 1: Python answer
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=5500))
    state, _ = step(state, TurnEnd(text="We use async event loops and worker pools.", turn_id="t_py_1", now_ms=6000))
    state, effects = step(state, CommitButton(now_ms=6100))
    py_req = next(e for e in effects if isinstance(e, RequestDecision))

    # Director follow-up
    state, _ = step(
        state,
        DecisionReady(
            token=py_req.token,
            decision={
                "action": "follow_up",
                "ack": "Good points on worker pools.",
                "question": "How do you handle task cancellation?",
                "target_skill": "Python",
                "covered_expectation_ids": ["asyncio"],
            },
            now_ms=6400,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_FOLLOWUP

    # 5. Skill 1 follow-up answer -> Director moves to Skill 2
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=7000))
    state, _ = step(state, TurnEnd(text="We handle asyncio.CancelledError cleanly.", turn_id="t_py_2", now_ms=7500))
    state, effects = step(state, CommitButton(now_ms=7600))
    s2_req = next(e for e in effects if isinstance(e, RequestDecision))

    state, _ = step(
        state,
        DecisionReady(
            token=s2_req.token,
            decision={
                "action": "new_topic",
                "ack": "Clear handling of cancellation.",
                "target_skill": "Distributed Systems",
                "question": "How do you design a reliable retry mechanism using backoff?",
            },
            now_ms=7900,
        ),
    )
    assert state.phase == ConductorPhase.SKILL_ANCHOR
    assert state.skill_names[state.current_skill_index] == "Distributed Systems"

    # 6. Skill 2: Distributed Systems answer -> Director closes
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=8500))
    state, _ = step(state, TurnEnd(text="We use exponential backoff with randomized jitter.", turn_id="t_ds_1", now_ms=9000))
    state, effects = step(state, CommitButton(now_ms=9100))
    close_req = next(e for e in effects if isinstance(e, RequestDecision))

    state, _ = step(
        state,
        DecisionReady(
            token=close_req.token,
            decision={
                "action": "close",
                "ack": "Exponential backoff with jitter prevents thundering herds.",
                "transition": "That concludes our technical topics.",
                "question": "Thank you for sharing your experience today.",
            },
            now_ms=9400,
        ),
    )
    assert state.phase in (ConductorPhase.CANDIDATE_QA, ConductorPhase.CLOSING)


# =============================================================================
# Remediations Part A: Director Prompt, Schema Contract, and "Right" Opener
# =============================================================================

def test_right_ack_opener_passes_both_validators():
    """An ack starting with 'Right,' passes both validate_director_decision and validate_and_format_ack."""
    from backend.app.services.interview_v2.conductor import validate_and_format_ack
    from backend.app.services.interview_v2.director import validate_director_decision

    ack_text = "Right, asyncio handles cooperative multitasking."
    candidate_answer = "I use asyncio for cooperative multitasking and high concurrency."
    question_text = "How do you handle concurrency in Python?"

    # 1. Conductor Ack validation
    val_ack, opener = validate_and_format_ack(
        raw_ack=ack_text,
        last_opener=None,
        candidate_answer=candidate_answer,
        question_text=question_text,
        action="follow_up",
    )
    assert val_ack != ""
    assert val_ack.startswith("Right,")

    # 2. Director decision validation
    dec = DirectorDecision(
        action="follow_up",
        ack=val_ack,
        transition="Let's explore that further.",
        question="How do you handle unhandled exceptions in background tasks?",
        target_skill="Python",
    )
    context = {
        "candidate_answer": candidate_answer,
        "current_skill": "Python",
        "asked_questions": [],
    }
    is_valid, errors = validate_director_decision(dec, context)
    assert is_valid is True, f"Validation failed with: {errors}"
    assert len(errors) == 0


def test_real_model_transition_deduplication():
    """Conductor strips duplicated question from transition and ensures Speak.text has it exactly once."""
    with open("tests/fixtures/director_bedrock_transition_raw.json") as f:
        fixture_dict = json.load(f)

    state = ConductorState()
    state, _ = step(state, SessionStart(session_id="test_trans_dedup", plan=make_test_plan(), now_ms=1000))
    state.phase = ConductorPhase.SKILL_ANCHOR
    state.current_skill_index = 0
    state.committed_answer = "I use asyncio for cooperative multitasking and multiprocessing for CPU tasks."
    state.awaiting_decision = True
    state.decision_token = "dec_trans_1"

    new_state, effects = validate_and_apply_decision(state, fixture_dict, now_ms=5000)
    speak = next(e for e in effects if isinstance(e, Speak))

    q = "How do you design a reliable retry mechanism using backoff?"
    assert speak.text.count(q) == 1, f"Expected question to appear exactly once, found:\n{speak.text}"
    assert "Now, let's shift to distributed systems." in speak.text
    assert new_state.phase == ConductorPhase.SKILL_ANCHOR
    assert new_state.skill_names[new_state.current_skill_index] == "Distributed Systems"


def test_generate_fallback_decision_filters_generic_verbs():
    """Fallback decision filters out generic verbs like 'use' and never produces 'trade-offs of use'."""
    from backend.app.services.interview_v2.director import generate_fallback_decision

    # 1. Answer with only generic verbs and words
    context1 = {
        "candidate_answer": "I use it to build things and do work.",
        "current_skill": "Distributed Systems",
        "remaining_topics": [],
        "available_competencies": [{"name": "Distributed Systems"}],
        "followups_used_in_topic": 0,
    }
    fb1 = generate_fallback_decision(context1)
    assert "trade-offs of use" not in fb1.question.lower()
    assert "Distributed Systems" in fb1.question

    # 2. Answer with technical concepts
    context2 = {
        "candidate_answer": "I use asyncio event loops for network I/O.",
        "current_skill": "Python",
        "remaining_topics": [],
        "available_competencies": [{"name": "Python"}],
        "followups_used_in_topic": 0,
    }
    fb2 = generate_fallback_decision(context2)
    assert "trade-offs of use" not in fb2.question.lower()
    assert "asyncio" in fb2.question.lower() or "event" in fb2.question.lower()


# =============================================================================
# Remediations Part B: Streaming Ack Contract
# =============================================================================

@pytest.mark.asyncio
async def test_streaming_ack_dict_payload_in_runner():
    """Runner on_stream_ack explicitly handles dict payloads and never outputs a dict literal."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner("sess_stream_dict_ack", script, ws, tts, llm_fn=None)

    req = RequestDecision(
        token="tok_stream_1",
        skill="Python",
        question_text="How do you handle concurrency in Python using asyncio versus multiprocessing?",
        answer_text="I use asyncio event loops for network I/O operations.",
        last_ack_opener="Right,",
    )

    dict_payload = {
        "action": "follow_up",
        "no_experience": False,
        "ack": "Asyncio event loops handle network I/O.",
    }

    async def mock_stream_call(**kwargs):
        callback = kwargs.get("on_ack_ready")
        if callback:
            callback(dict_payload)
        return (
            {
                "action": "follow_up",
                "ack": "Asyncio event loops handle network I/O.",
                "question": "How do you handle task cancellation?",
            },
            {"ttft_ms": 100},
        )

    with patch(
        "backend.app.services.interview_v2.director.stream_decision_with_ack_first",
        side_effect=mock_stream_call,
    ):
        await runner._call_decision_llm(req)

        ack_event = None
        for _ in range(5):
            ev = await asyncio.wait_for(runner.queue.get(), timeout=1.0)
            if isinstance(ev, AckReady):
                ack_event = ev
                break

        assert ack_event is not None
        assert not ack_event.text.startswith("{")
        assert "action" not in ack_event.text
        assert "asyncio event loops" in ack_event.text.lower()

        # Step conductor with AckReady and verify SpeakAck text
        state = ConductorState()
        state, _ = step(state, SessionStart(session_id="test_ack_speak", plan=make_test_plan(), now_ms=1000))
        state.phase = ConductorPhase.SKILL_ANCHOR
        state.awaiting_decision = True
        state.decision_token = req.token
        state.committed_answer = req.answer_text

        new_state, effects = step(state, ack_event)
        speak_ack = next(e for e in effects if isinstance(e, SpeakAck))
        assert "asyncio event loops" in speak_ack.text.lower()
        assert not speak_ack.text.startswith("{")


@pytest.mark.asyncio
async def test_streaming_ack_short_dict_literal_not_spoken_verbatim():
    """Short dict payload whose string length is <= 12 words must not be spoken as a dict literal."""
    ws = FakeWebSocket()
    tts = FakeAuraTTSClient()
    script = make_test_script()

    runner = SessionRunner("sess_stream_short_dict", script, ws, tts, llm_fn=None)

    req = RequestDecision(
        token="tok_stream_short",
        skill="Python",
        question_text="How do you handle concurrency in Python using asyncio versus multiprocessing?",
        answer_text="We use uvloop with worker pools for high concurrency.",
    )

    # A dict whose repr: "{'action': 'follow_up', 'ack': 'Right, uvloop.'}" is <= 12 words!
    short_dict = {"action": "follow_up", "ack": "Right, uvloop."}

    async def mock_stream_short(**kwargs):
        callback = kwargs.get("on_ack_ready")
        if callback:
            callback(short_dict)
        return (short_dict, {"ttft_ms": 90})

    with patch(
        "backend.app.services.interview_v2.director.stream_decision_with_ack_first",
        side_effect=mock_stream_short,
    ):
        await runner._call_decision_llm(req)

        ack_event = None
        for _ in range(5):
            ev = await asyncio.wait_for(runner.queue.get(), timeout=1.0)
            if isinstance(ev, AckReady):
                ack_event = ev
                break

        assert ack_event is not None
        assert "{" not in ack_event.text
        assert "action" not in ack_event.text
        assert "uvloop" in ack_event.text.lower()


# =============================================================================
# Remediations Part C: Agenda Preference & Affirmative Intent Parsing
# =============================================================================

def test_agenda_preference_parsing_patterns():
    """extract_prioritized_skill accurately handles preference expressions and negation objects."""
    skills = ["Python", "Distributed Systems"]

    # 1. "prefer X over Y"
    assert extract_prioritized_skill("I'd prefer distributed systems over Python", skills) == "Distributed Systems"
    assert extract_prioritized_skill("I prefer Python over distributed systems", skills) == "Python"

    # 2. "rather X than Y"
    assert extract_prioritized_skill("I'd rather do Distributed Systems than Python", skills) == "Distributed Systems"

    # 3. "X instead of Y"
    assert extract_prioritized_skill("Can we do distributed systems instead of Python?", skills) == "Distributed Systems"

    # 4. "X is better than Y"
    assert extract_prioritized_skill("Distributed systems is better than Python for me", skills) == "Distributed Systems"

    # 5. "focus on X"
    assert extract_prioritized_skill("Let's focus on Distributed Systems today", skills) == "Distributed Systems"


def test_agenda_common_affirmatives_not_negative():
    """classify_agenda_intent classifies polite affirmatives containing 'no/not' as affirmative."""
    from backend.app.services.interview_v2.conductor import classify_agenda_intent

    assert classify_agenda_intent("No problem, let's go") == "affirmative"
    assert classify_agenda_intent("No worries, sounds good") == "affirmative"
    assert classify_agenda_intent("I'm ready, no changes") == "affirmative"
    assert classify_agenda_intent("Not sure, but yes") == "affirmative"
    assert classify_agenda_intent("Sounds great, let's start") == "affirmative"

    # Genuine negative intents
    assert classify_agenda_intent("No, can we change the agenda?") == "negative"
    assert classify_agenda_intent("Actually, I'd rather adjust the topics") == "negative"
    assert classify_agenda_intent("I don't want Python") == "negative"


# =============================================================================
# Remediations Part D: Acceptance Gate for Real Bedrock Transition Fixture
# =============================================================================

@pytest.mark.asyncio
async def test_real_bedrock_fixture_acceptance_gate():
    """Acceptance Gate: Real Bedrock transition output fixture passes validation cleanly."""
    with open("tests/fixtures/director_bedrock_transition_raw.json") as f:
        raw_fixture = json.load(f)

    context = {
        "candidate_answer": "I use asyncio for cooperative multitasking and multiprocessing for CPU tasks.",
        "current_skill": "Python",
        "current_question": "How do you handle concurrency in Python using asyncio versus multiprocessing?",
        "remaining_topics": ["Distributed Systems"],
        "available_competencies": [
            {"name": "Python"},
            {"name": "Distributed Systems", "anchor_question": "How do you design a reliable retry mechanism using backoff?"},
        ],
        "asked_questions": [],
        "followups_used_in_topic": 1,
    }

    emitted_ack = []

    def on_ack_callback(payload):
        emitted_ack.append(payload)

    # Mock the transport stream to yield the raw fixture and call on_ack_ready
    async def mock_stream(**kwargs):
        cb = kwargs.get("on_ack_ready")
        if cb:
            cb({"action": raw_fixture["action"], "ack": raw_fixture["ack"], "no_experience": False})
        return raw_fixture, {"ttft_ms": 110, "provider": "bedrock", "model_name": "apac.amazon.nova-pro-v1:0"}

    with patch("backend.app.services.interview_v2.director.stream_decision_with_ack_first", side_effect=mock_stream):
        decision, metrics = await generate_director_decision(
            context=context,
            on_ack_ready=on_ack_callback,
        )

        # 1. Action coerced to canonical new_topic
        assert decision.action == "new_topic"

        # 2. Question is the Distributed Systems anchor
        assert decision.question == "How do you design a reliable retry mechanism using backoff?"

        # 3. Validation passed without fallback
        assert metrics["validation_passed"] is True
        assert metrics["fallback_reason"] is None

        # 4. Analysis summary is populated from the string analysis
        assert decision.analysis.answer_summary == raw_fixture["analysis"]

        # 5. Emitted ack callback is not a dict string
        assert len(emitted_ack) > 0
        ack_payload = emitted_ack[0]
        if isinstance(ack_payload, dict):
            ack_str = ack_payload.get("ack", "")
        elif isinstance(ack_payload, (list, tuple)):
            ack_str = ack_payload[1]
        else:
            ack_str = str(ack_payload)
        assert not ack_str.startswith("{")

        # 6. Apply to conductor: question appears in Speak.text exactly once
        state = ConductorState()
        state, _ = step(state, SessionStart(session_id="test_acc_gate", plan=make_test_plan(), now_ms=1000))
        state.phase = ConductorPhase.SKILL_ANCHOR
        state.current_skill_index = 0
        state.committed_answer = context["candidate_answer"]
        state.awaiting_decision = True
        state.decision_token = "dec_acc_1"

        new_state, effects = validate_and_apply_decision(state, decision.to_dict(), now_ms=6000)
        speak = next(e for e in effects if isinstance(e, Speak))
        q_count = speak.text.count("How do you design a reliable retry mechanism using backoff?")
        assert q_count == 1, f"Question appeared {q_count} times in speak.text: {speak.text}"


@pytest.mark.skipif(not os.getenv("RUN_LIVE_DIRECTOR"), reason="Live Bedrock test gated by RUN_LIVE_DIRECTOR=1")
@pytest.mark.asyncio
async def test_gated_live_director_latency():
    """Gated live test with real Bedrock credentials measuring fast ack and director latency."""
    token = get_bedrock_bearer_token()
    assert token, "AWS_BEARER_TOKEN_BEDROCK must be set for live test"

    context = {
        "candidate_answer": "I use asyncio for cooperative multitasking with event loops and multiprocessing for CPU-bound tasks.",
        "current_skill": "Python",
        "current_question": "How do you handle concurrency in Python using asyncio versus multiprocessing?",
        "remaining_topics": ["Distributed Systems"],
        "available_competencies": [
            {"name": "Python"},
            {"name": "Distributed Systems", "anchor_question": "How do you design a reliable retry mechanism using backoff?"},
        ],
        "asked_questions": [],
        "followups_used_in_topic": 1,
    }

    t0 = time.perf_counter()
    decision, metrics = await director.generate_director_decision(context=context)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\nLive Bedrock Director result: action={decision.action}, total={elapsed_ms:.1f}ms, metrics={metrics}")
    assert decision.action in ("follow_up", "new_topic", "clarify", "close")
    assert decision.question != ""
    assert metrics["validation_passed"] is True
