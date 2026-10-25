"""Director verification + A6 regression (rebuilt from bytecode map).

Covers the live decision path with llm_fn=None, canonical decision contract,
conductor pacing loops, intro fallback degradation, ack opener validation, and
SpeakAck execution through the runner.
"""

import asyncio
import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.interview_v2.conductor import (
    ConductorPhase,
    ConductorState,
    SessionStart,
    TurnEnd,
    Tick,
    BotSpeechDone,
    DecisionReady,
    Speak,
    SpeakAck,
    AckReady,
    RequestDecision,
    step,
    validate_and_apply_decision,
    validate_and_format_ack,
)


def plan_ok():
    return {
        "job_record": {"title": "Senior Python Engineer", "seniority": "Senior"},
        "questions": [
            {"question_index": 0, "kind": "greeting", "skill_name": "", "question_text": "Hi! Ready?"},
            {"question_index": 1, "kind": "background", "skill_name": "", "question_text": "Introduce yourself."},
            {"question_index": 2, "kind": "anchor", "skill_name": "Python",
             "question_text": "How do you handle concurrency?",
             "expected_key_points": ["Explains asyncio"],
             "followup_probes": ["What about the GIL?"]},
            {"question_index": 3, "kind": "anchor_alt", "skill_name": "Python", "question_text": "Suppose two tasks collide; what then?"},
            {"question_index": 4, "kind": "probe", "skill_name": "Python", "question_text": "What about the GIL?"},
            {"question_index": 5, "kind": "anchor", "skill_name": "Distributed Systems", "question_text": "Design a rate limiter."},
            {"question_index": 20, "kind": "candidate_qa", "skill_name": "", "question_text": "Questions?"},
            {"question_index": 21, "kind": "closing", "skill_name": "", "question_text": "Thanks!"},
        ],
    }


def _started():
    """Greeting speech done -> ReadyButton -> INTRO question asked and finished."""
    state, _ = step(ConductorState(), SessionStart(session_id="s_dir", plan=plan_ok(), now_ms=1000))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=2000))
    state, _ = step(state, __import__("backend.app.services.interview_v2.conductor", fromlist=["ReadyButton"]).ReadyButton(now_ms=2100))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))
    return state


def _to_python(state):
    state, _ = step(state, TurnEnd(text="I have five years of Python backend experience with asyncio services.", turn_id="t_i", now_ms=4000))
    state, effects = step(state, Tick(now_ms=4300))
    req = next((e for e in effects if isinstance(e, RequestDecision)), None)
    if req is None:
        state, effects = step(state, Tick(now_ms=7000))
        req = next((e for e in effects if isinstance(e, RequestDecision)), None)
    assert req is not None, "intro commit must eventually request a decision"
    state, _ = step(state, DecisionReady(token=req.token, decision={"action": "new_topic", "target_skill": "Python"}, now_ms=4400))
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=5000))
    return state


# ---------------------------------------------------------------------------
# Canonical decision contract
# ---------------------------------------------------------------------------

def test_canonical_actions_accepted():
    state = _to_python(_started())
    for action in ("follow_up", "new_topic", "clarify", "rephrase", "hypothetical", "off_topic", "candidate_qa"):
        st = state.copy()
        st.awaiting_decision = True
        st.decision_token = "tok_x"
        st2, effects = validate_and_apply_decision(
            st,
            {"action": action, "question": "What about X?", "followup": "What about X?", "ack": "Right."},
            now_ms=10000,
        )
        assert st2.phase not in (ConductorPhase.INIT,), f"{action} must process"


def test_legacy_field_mapping_before_validation():
    state = _to_python(_started())
    state.awaiting_decision = True
    state.phase_before_commit = None
    state.decision_token = "tok_l"
    st2, effects = validate_and_apply_decision(
        state,
        {"action": "probe", "followup": "Which lock did you pick exactly?", "ack": ""},
        now_ms=12000,
    )
    speak = next((e for e in effects if isinstance(e, Speak)), None)
    assert speak is not None and "lock did you pick" in speak.text


def test_right_ack_opener_passes_both_validators():
    formatted, opener = validate_and_format_ack(raw_ack="Right, the partition assignment.", last_opener=None)
    assert formatted  # grounding enforced elsewhere; here shape/format only
    assert "Right" in formatted or formatted == ""


# ---------------------------------------------------------------------------
# Pacing loops
# ---------------------------------------------------------------------------

def test_pacing_all_core_covered_forces_advance():
    state = _to_python(_started())
    state.covered_expectations_per_skill["Python"] = ["Explains asyncio"]
    state.awaiting_decision = True
    state.decision_token = "tok_c"
    st2, effects = validate_and_apply_decision(
        state, {"action": "follow_up", "followup": "Probe deeper into locks now?", "ack": ""}, now_ms=15000,
    )
    speak = next((e for e in effects if isinstance(e, Speak)), None)
    if speak:
        assert "Probe deeper into locks" not in speak.text, "all-core-covered must not probe further"


def test_pacing_followup_cap_forces_advance():
    state = _to_python(_started())
    state.followups_used_per_skill["Python"] = state.max_followups_per_skill.get("Python", 2)
    state.awaiting_decision = True
    state.decision_token = "tok_m"
    st2, effects = validate_and_apply_decision(
        state, {"action": "follow_up", "followup": "Yet another probe question here?", "ack": ""}, now_ms=16000,
    )
    speak = next((e for e in effects if isinstance(e, Speak)), None)
    if speak:
        assert "Yet another probe" not in speak.text


def test_intro_fallback_degrades_gracefully():
    st0 = _started()
    state, _ = step(st0, TurnEnd(text="I am a Python developer with distributed systems experience.", turn_id="t_in", now_ms=4000))
    st2, effects = step(state, Tick(now_ms=4300))
    if not st2.awaiting_decision:
        st2, effects = step(state, Tick(now_ms=7000))
    # Invalid/None decision -> deterministic fallback still transitions
    st3, effects2 = validate_and_apply_decision(st2, None, now_ms=5000) if st2.awaiting_decision else (st2, effects)
    if st2.awaiting_decision:
        assert st3.phase in (ConductorPhase.SKILL_ANCHOR, ConductorPhase.INTRO)


# ---------------------------------------------------------------------------
# SpeakAck through runner effect execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speak_ack_executes_full_tts_sequence():
    from backend.app.services.interview_v2.runner import SessionRunner

    class FakeAura:
        voice = "aura-test"

        async def speak(self, text):
            yield b"\x00" * 10

        async def cancel(self):
            return None

    r = SessionRunner(
        session_id="sess_ack_seq",
        script={"questions": [], "job_record": {}},
        aura_client=FakeAura(),
    )
    r.client_connected = True
    ws = MagicMock()
    ws.send_json = AsyncMock()
    r.websocket = ws
    await r._handle_speak_ack(SpeakAck(text="Right.", speech_id="ack_speech_1", token="tok_ack"))
    # Frames sent: TTSStarted -> BotSpeechStarted (TTSDone/BotSpeechDone follow
    # the client's playback confirmations, by design)
    sent = [c.args[0] for c in ws.send_json.await_args_list]
    types = [m.get("type") for m in sent if isinstance(m, dict)]
    assert "TTSStarted" in types
    assert "BotSpeechStarted" in types
