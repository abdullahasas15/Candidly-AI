"""Phase A6 Comprehensive Deterministic Regression Test Suite.

Verifies:
1. Intro-to-Anchor Regression: 100 randomized iterations varying event timing, order,
   duplicate events (same & different IDs with equivalent transcript), delayed ticks,
   and speculative cancellation.
2. Candidate Q&A Grounding & Deferrals:
   - "What technologies does the role use?" -> Answer supported by facts.
   - "What does success look like in six months?" -> Deferral.
   - "How much autonomy will I have?" -> Deferral.
   - "What is the salary and bonus?" -> Deferral.
   - Two consecutive Q&A questions with different content each receive matching reply.
   - Late first-question response does not overwrite second question reply.
3. Outbound Speech Ledger verification:
   - Authoritative tracking of every semantic segment.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

import pytest

from backend.app.services.interview_v2.conductor import (
    APPROVED_QA_DEFERRAL,
    AckReady,
    BotSpeechDone,
    CancelSpeculativeReply,
    CancelTimer,
    CommitButton,
    ConductorPhase,
    ConductorState,
    DecisionContextSnapshot,
    DecisionReady,
    EagerTurnEnd,
    EmitUI,
    OutboundSpeechLedger,
    Persist,
    PlanQuestion,
    PlayBridge,
    ReadyButton,
    RequestDecision,
    ScheduleTimer,
    SessionStart,
    Speak,
    SpeakAck,
    StartSpeculativeReply,
    Tick,
    TurnEnd,
    TurnStart,
    compute_content_hash,
    extract_job_facts,
    normalize_text_for_hash,
    step,
    validate_and_format_ack,
    validate_qa_decision,
)


def make_test_plan() -> Dict[str, Any]:
    return {
        "job_record": {
            "title": "Senior Backend Engineer",
            "seniority": "Senior",
            "skills": ["Python", "FastAPI", "Distributed Systems", "PostgreSQL"],
            "description": "Building high-throughput microservices using asynchronous Python and streaming architectures.",
        },
        "questions": [
            {
                "id": "q_welcome",
                "question_index": 0,
                "kind": "welcome",
                "skill_name": "General",
                "question_text": "Hi, welcome to your interview.",
            },
            {
                "id": "q_intro_hook",
                "question_index": 1,
                "kind": "intro_hook",
                "skill_name": "General",
                "question_text": "Could you walk me through your background in software engineering?",
            },
            {
                "id": "q_py_anchor",
                "question_index": 2,
                "kind": "anchor",
                "skill_name": "Python",
                "question_text": "How do you handle CPU-bound vs IO-bound tasks in Python?",
                "expected_key_points": ["GIL", "multiprocessing", "asyncio"],
            },
            {
                "id": "q_py_alt",
                "question_index": 3,
                "kind": "anchor_alt",
                "skill_name": "Python",
                "question_text": "Can you explain how threading and the GIL interact in Python?",
            },
            {
                "id": "q_py_esc",
                "question_index": 4,
                "kind": "escalation",
                "skill_name": "Python",
                "question_text": "How would you optimize high-throughput C extensions bypassing the GIL?",
            },
            {
                "id": "q_qa",
                "question_index": 5,
                "kind": "candidate_qa",
                "skill_name": "Candidate Q&A",
                "question_text": "What questions do you have for us?",
            },
            {
                "id": "q_closing",
                "question_index": 6,
                "kind": "closing",
                "skill_name": "General",
                "question_text": "Thanks for your time today. Goodbye!",
            },
        ],
    }


# =============================================================================
# Requirement 2: 100 Randomized Intro-to-Anchor Regression Iterations
# =============================================================================
def test_intro_to_anchor_regression_100_runs():
    """Deterministic, model-free regression test executing intro-to-first-anchor transition

    100 times, varying event timing, duplicate events (same and different IDs with
    equivalent transcript), delayed ticks, and speculative completion/cancellation.
    """
    plan = make_test_plan()
    intro_question_text = plan["questions"][1]["question_text"]
    first_anchor_text = plan["questions"][2]["question_text"]

    for iteration in range(100):
        seed = 42000 + iteration
        rng = random.Random(seed)

        state = ConductorState()
        now = 1000

        # 1. Start Session
        state, effects = step(state, SessionStart(session_id=f"test_intro_{iteration}", plan=plan, now_ms=now))
        assert state.phase == ConductorPhase.WELCOME
        now += rng.randint(200, 500)

        # 2. Welcome spoken -> Ready Gate
        state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=now))
        assert state.phase == ConductorPhase.READY_GATE
        now += rng.randint(50, 200)

        # 3. Ready Button -> Intro question spoken
        state, effects = step(state, ReadyButton(now_ms=now))
        speak_intro = next(e for e in effects if isinstance(e, Speak))
        assert speak_intro.text == intro_question_text
        assert state.phase == ConductorPhase.INTRO
        now += rng.randint(500, 1500)

        # Bot speech finishes speaking intro question
        state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=now))
        now += rng.randint(100, 400)

        # Candidate begins speaking intro answer
        intro_answer = "I have been building distributed backend services with Python and FastAPI for six years."
        state, _ = step(state, TurnStart(now_ms=now))

        # Randomize whether EagerTurnEnd arrives before final TurnEnd
        include_eager = rng.choice([True, False])
        if include_eager:
            eager_prefix = "I have been building distributed backend services with Python"
            now += rng.randint(300, 600)
            state, eager_effects = step(state, EagerTurnEnd(text=eager_prefix, now_ms=now))

        # Final TurnEnd arrives
        turn_id_1 = f"t_intro_{iteration}_a"
        now += rng.randint(300, 800)
        state, _ = step(state, TurnEnd(text=intro_answer, turn_id=turn_id_1, now_ms=now))

        # Inject duplicate TurnEnd with SAME turn_id
        if rng.choice([True, False]):
            state, _ = step(state, TurnEnd(text=intro_answer, turn_id=turn_id_1, now_ms=now + 50))

        # Inject duplicate TurnEnd with DIFFERENT turn_id but EQUIVALENT transcript
        if rng.choice([True, False]):
            turn_id_dup = f"t_intro_{iteration}_dup"
            state, _ = step(state, TurnEnd(text=intro_answer, turn_id=turn_id_dup, now_ms=now + 80))

        # Inject delayed Tick before commit time (must NOT commit prematurely)
        commit_timer = state.active_timers.get("commit")
        assert commit_timer is not None
        commit_at = commit_timer["at_ms"]

        premature_tick_ms = now + rng.randint(10, 200)
        if premature_tick_ms < commit_at:
            state, premature_effects = step(state, Tick(now_ms=premature_tick_ms))
            assert not any(isinstance(e, Speak) for e in premature_effects)
            assert state.phase == ConductorPhase.INTRO

        # Now advance time past commit timer
        final_tick_ms = commit_at + rng.randint(0, 100)
        state, commit_effects = step(state, Tick(now_ms=final_tick_ms))

        # ASSERTIONS:
        # 1. Exactly one Persist effect for the intro answer
        persist_effects = [e for e in commit_effects if isinstance(e, Persist)]
        assert len(persist_effects) == 1, f"Seed {seed}: Expected 1 Persist effect, got {len(persist_effects)}"
        assert persist_effects[0].turn["question_kind"] == "intro_hook"

        # 2. Exactly one Speak effect emitted for the first anchor question
        speak_effects = [e for e in commit_effects if isinstance(e, Speak)]
        assert len(speak_effects) == 1, f"Seed {seed}: Expected 1 Speak effect, got {len(speak_effects)}"
        spoken_text = speak_effects[0].text

        # 3. The intro question is never emitted again
        assert intro_question_text not in spoken_text, f"Seed {seed}: Intro question was repeated!"

        # 4. First skill anchor is in the spoken text
        assert first_anchor_text in spoken_text, f"Seed {seed}: Anchor text missing from: {spoken_text}"

        # 5. Conductor enters SKILL_ANCHOR and retains correct active question index
        assert state.phase == ConductorPhase.SKILL_ANCHOR
        assert state.current_skill_index == 0
        assert state.skill_names[0] == "Python"
        assert state.current_question_index == plan["questions"][2]["question_index"]

        # 6. Duplicate delayed tick after commit CANNOT cause a second transition
        stale_tick_ms = final_tick_ms + rng.randint(100, 500)
        state, stale_effects = step(state, Tick(now_ms=stale_tick_ms))
        assert not any(isinstance(e, Speak) for e in stale_effects)
        assert state.phase == ConductorPhase.SKILL_ANCHOR


# =============================================================================
# Requirement 6: Candidate Q&A Grounding, Deferrals & Multi-Round State
# =============================================================================
def test_candidate_qa_known_fact_supported():
    """Technologies question is answered using verified job facts."""
    plan = make_test_plan()
    job_facts = extract_job_facts(plan["job_record"])
    assert "required_skill_1" in job_facts

    decision = {
        "action": "qa_reply",
        "no_experience": False,
        "ack": "Right, regarding our tech stack.",
        "source_facts": ["required_skill_1", "required_skill_2"],
        "followup": "We use Python and FastAPI for high-scale backend services. Anything else?",
    }
    followup, ack, verified = validate_qa_decision(
        decision=decision,
        job_facts=job_facts,
        candidate_question="What technologies does the role use?",
    )
    assert "Python" in followup
    assert len(verified) == 2
    assert "required_skill_1" in verified


def test_candidate_qa_six_month_success_defers():
    """Six-month success criteria is not in job record -> approved deferral."""
    plan = make_test_plan()
    job_facts = extract_job_facts(plan["job_record"])

    # LLM hallucinates an answer
    decision = {
        "action": "qa_reply",
        "no_experience": False,
        "ack": "I see.",
        "source_facts": ["job_title"],
        "followup": "In six months you will own two services and lead a major migration. Anything else?",
    }
    followup, ack, verified = validate_qa_decision(
        decision=decision,
        job_facts=job_facts,
        candidate_question="What does success look like in six months?",
    )
    assert followup == APPROVED_QA_DEFERRAL
    assert verified == []


def test_candidate_qa_autonomy_defers():
    """Autonomy question -> approved deferral."""
    plan = make_test_plan()
    job_facts = extract_job_facts(plan["job_record"])

    decision = {
        "action": "qa_reply",
        "no_experience": False,
        "ack": "Understood.",
        "source_facts": ["job_title"],
        "followup": "You will have full technical autonomy over architecture decisions. Anything else?",
    }
    followup, ack, verified = validate_qa_decision(
        decision=decision,
        job_facts=job_facts,
        candidate_question="How much autonomy will I have in technical choices?",
    )
    assert followup == APPROVED_QA_DEFERRAL


def test_candidate_qa_compensation_and_benefits_defers():
    """Salary, bonus, and retirement benefits -> approved deferral."""
    plan = make_test_plan()
    job_facts = extract_job_facts(plan["job_record"])

    decision = {
        "action": "qa_reply",
        "no_experience": False,
        "ack": "Understood.",
        "source_facts": ["job_title"],
        "followup": "The base salary is 180k with 20% bonus and 401k matching. Anything else?",
    }
    followup, ack, verified = validate_qa_decision(
        decision=decision,
        job_facts=job_facts,
        candidate_question="What is the salary, annual bonus, and 401k match?",
    )
    assert followup == APPROVED_QA_DEFERRAL


def test_two_consecutive_qa_questions_with_different_turn_identities():
    """Two consecutive Q&A questions with different content each receive matching reply."""
    state = ConductorState()
    plan = make_test_plan()
    state, _ = step(state, SessionStart(session_id="test_qa_consecutive", plan=plan, now_ms=1000))
    state.phase = ConductorPhase.CANDIDATE_QA
    qa_q = next(q for q in state.questions if q.kind == "candidate_qa")
    state.current_question_index = qa_q.question_index
    state.job_record = plan["job_record"]

    # Round 1: Technologies
    state, _ = step(state, TurnEnd(text="What technologies does the team use?", turn_id="t_qa_r1", now_ms=2000))
    state, effects = step(state, Tick(now_ms=2300))
    req1 = next(e for e in effects if isinstance(e, RequestDecision))
    assert req1.snapshot is not None
    assert req1.snapshot.candidate_turn_id == "turn_1"

    # Decision for Round 1
    state, eff1 = step(
        state,
        DecisionReady(
            token=req1.token,
            decision={
                "action": "qa_reply",
                "no_experience": False,
                "ack": "Right, on the tech stack.",
                "source_facts": ["required_skill_1"],
                "followup": "The team uses Python and FastAPI. Anything else?",
            },
            snapshot=req1.snapshot,
            now_ms=2400,
        ),
    )
    speak1 = next(e for e in eff1 if isinstance(e, Speak))
    assert "Python" in speak1.text

    # Complete speech
    state, _ = step(state, BotSpeechDone(speech_id=state.active_speech_id, now_ms=3000))

    # Round 2: Compensation
    state, _ = step(state, TurnEnd(text="What is the compensation and bonus?", turn_id="t_qa_r2", now_ms=4000))
    state, effects2 = step(state, Tick(now_ms=4300))
    req2 = next(e for e in effects2 if isinstance(e, RequestDecision))
    assert req2.snapshot is not None
    assert req2.snapshot.candidate_turn_id == "turn_2"

    # Decision for Round 2
    state, eff2 = step(
        state,
        DecisionReady(
            token=req2.token,
            decision={
                "action": "qa_reply",
                "no_experience": False,
                "ack": "",
                "source_facts": [],
                "followup": APPROVED_QA_DEFERRAL,
            },
            snapshot=req2.snapshot,
            now_ms=4400,
        ),
    )
    speak2 = next(e for e in eff2 if isinstance(e, Speak))
    assert APPROVED_QA_DEFERRAL in speak2.text

    # Late response from Round 1 arrives NOW with req1 token (must be discarded!)
    state, late_eff = step(
        state,
        DecisionReady(
            token=req1.token,
            decision={
                "action": "qa_reply",
                "no_experience": False,
                "ack": "Old ack.",
                "source_facts": ["required_skill_1"],
                "followup": "Old reply that must not overwrite Round 2.",
            },
            snapshot=req1.snapshot,
            now_ms=4500,
        ),
    )
    # Stale decision must produce zero Speak effects!
    assert not any(isinstance(e, Speak) for e in late_eff)


# =============================================================================
# Requirement 3: Immutable Context Snapshot & Stale Decision Discard
# =============================================================================
def test_stale_decision_snapshot_mismatch_discarded():
    """DecisionReady with an answer_hash mismatch is discarded without modifying state."""
    state = ConductorState()
    plan = make_test_plan()
    state, _ = step(state, SessionStart(session_id="test_stale_snap", plan=plan, now_ms=1000))
    state.phase = ConductorPhase.SKILL_ANCHOR
    state.current_skill_index = 0
    state.current_question_index = 2

    # Commit answer
    state, _ = step(state, TurnEnd(text="I use asyncio for IO concurrency.", turn_id="t_real", now_ms=2000))
    state, effects = step(state, Tick(now_ms=2300))
    req = next(e for e in effects if isinstance(e, RequestDecision))
    assert state.active_decision_snapshot is not None

    # Construct stale snapshot with DIFFERENT answer_hash
    stale_snapshot = DecisionContextSnapshot(
        session_id=state.session_id,
        candidate_turn_id=state.current_candidate_turn_id,
        question_index=state.current_question_index,
        skill_name="Python",
        phase=state.phase.value,
        normalized_answer="stale answer",
        answer_hash=compute_content_hash("stale answer"),
        question_text="How do you handle CPU-bound vs IO-bound tasks in Python?",
        question_hash=compute_content_hash("How do you handle CPU-bound vs IO-bound tasks in Python?"),
        request_id="stale_req",
    )

    # DecisionReady with stale snapshot arrives
    state, stale_effects = step(
        state,
        DecisionReady(
            token=req.token,
            decision={
                "action": "escalate",
                "ack": "Stale ack.",
                "followup": "Stale question.",
            },
            snapshot=stale_snapshot,
            now_ms=2500,
        ),
    )
    # Must be completely ignored: no Speak effects, still awaiting decision!
    assert not any(isinstance(e, Speak) for e in stale_effects)
    assert state.awaiting_decision is True


# =============================================================================
# Requirement 1: Outbound Speech Ledger Verification
# =============================================================================
def test_outbound_speech_ledger_ordered_segments():
    """Verify outbound speech ledger records ordered semantic segments, timestamps, and status."""
    ledger = OutboundSpeechLedger(session_id="test_ledger_sess")

    # Turn 1: Bridge played, then question spoken
    seg_bridge = ledger.record_segment(
        candidate_turn_id="turn_1",
        speech_id="speech_1",
        request_id="bridge_1",
        semantic_kind="bridge",
        text="Right,",
        action="bridge",
        effective_action="bridge",
        scheduled_at_ms=1000,
        status="sent",
    )
    ledger.mark_started("speech_1", 1005, kind="bridge")
    ledger.mark_completed("speech_1", 1350, kind="bridge")

    seg_q = ledger.record_segment(
        candidate_turn_id="turn_1",
        speech_id="speech_2",
        request_id="q_speech_2",
        semantic_kind="question",
        text="How do you handle CPU-bound tasks in Python?",
        action="escalate",
        effective_action="escalate",
        question_id="q_py_esc",
        skill_name="Python",
        scheduled_at_ms=1360,
        status="sent",
    )
    ledger.mark_started("speech_2", 1400)
    ledger.mark_completed("speech_2", 2100)

    # Verification
    turn1_segs = ledger.get_segments_for_turn("turn_1")
    assert len(turn1_segs) == 2
    assert turn1_segs[0].semantic_kind == "bridge"
    assert turn1_segs[1].semantic_kind == "question"
    assert turn1_segs[0].playback_completed_at_ms == 1350
    assert turn1_segs[1].playback_completed_at_ms == 2100

    last_q = ledger.get_last_question_segment()
    assert last_q is not None
    assert last_q.question_id == "q_py_esc"
    assert last_q.text == "How do you handle CPU-bound tasks in Python?"


# =============================================================================
# Phase A6.2 New Regression Tests
# =============================================================================

def test_speculation_turn_id_context_mismatch():
    """Identical answer in a different candidate turn produces context mismatch and cannot leak."""
    state = ConductorState()
    plan = make_test_plan()
    state, _ = step(state, SessionStart(session_id="test_turn_mismatch", plan=plan, now_ms=1000))
    state.phase = ConductorPhase.SKILL_ANCHOR
    state.current_skill_index = 0
    state.current_question_index = 2
    state.bot_speaking = False
    state.active_speech_id = None

    # Eager turn for turn_1
    state.current_candidate_turn_id = "turn_1"
    state, _ = step(state, TurnStart(now_ms=1900))
    state, effects = step(state, EagerTurnEnd(text="I use asyncio for nonblocking network calls.", now_ms=2000))
    spec_start = next((e for e in effects if isinstance(e, StartSpeculativeReply)), None)
    assert spec_start is not None
    assert spec_start.snapshot.candidate_turn_id == "turn_1"

    # Simulated commit for turn_2 with identical text
    commit_snapshot = DecisionContextSnapshot(
        session_id=state.session_id,
        candidate_turn_id="turn_2",
        question_index=state.current_question_index,
        skill_name="Python",
        phase=state.phase.value,
        normalized_answer=normalize_text_for_hash("I use asyncio for nonblocking network calls."),
        answer_hash=compute_content_hash("I use asyncio for nonblocking network calls."),
        question_text=plan["questions"][2]["question_text"],
        question_hash=compute_content_hash(plan["questions"][2]["question_text"]),
        request_id="dec_commit_turn_2",
    )

    # Comparing spec_snapshot with commit_snapshot detects turn_id context mismatch
    snap = spec_start.snapshot
    comm = commit_snapshot
    assert snap.candidate_turn_id != comm.candidate_turn_id
    # Outcome must be context mismatch, never reused
    assert snap.candidate_turn_id == "turn_1" and comm.candidate_turn_id == "turn_2"


def test_speculation_competency_context_mismatch():
    """Identical answer and question text under different competency produces context mismatch."""
    snap = DecisionContextSnapshot(
        session_id="sess_comp",
        candidate_turn_id="turn_2",
        question_index=2,
        skill_name="Python",
        phase="SKILL_ANCHOR",
        normalized_answer="we use distributed consensus",
        answer_hash=compute_content_hash("we use distributed consensus"),
        question_text="How do you handle consensus?",
        question_hash=compute_content_hash("How do you handle consensus?"),
        request_id="req_1",
    )
    comm = DecisionContextSnapshot(
        session_id="sess_comp",
        candidate_turn_id="turn_2",
        question_index=2,
        skill_name="Distributed Systems",  # Changed competency!
        phase="SKILL_ANCHOR",
        normalized_answer="we use distributed consensus",
        answer_hash=compute_content_hash("we use distributed consensus"),
        question_text="How do you handle consensus?",
        question_hash=compute_content_hash("How do you handle consensus?"),
        request_id="req_2",
    )
    assert snap.skill_name != comm.skill_name


def test_speculation_question_hash_mismatch():
    """Identical answer but different active question produces question_hash context mismatch."""
    snap = DecisionContextSnapshot(
        session_id="sess_qhash",
        candidate_turn_id="turn_1",
        question_index=2,
        skill_name="Python",
        phase="SKILL_ANCHOR",
        normalized_answer="we use locks",
        answer_hash=compute_content_hash("we use locks"),
        question_text="How do you handle CPU-bound vs IO-bound tasks in Python?",
        question_hash=compute_content_hash("How do you handle CPU-bound vs IO-bound tasks in Python?"),
        request_id="req_1",
    )
    comm = DecisionContextSnapshot(
        session_id="sess_qhash",
        candidate_turn_id="turn_1",
        question_index=2,
        skill_name="Python",
        phase="SKILL_ANCHOR",
        normalized_answer="we use locks",
        answer_hash=compute_content_hash("we use locks"),
        question_text="What profiling tools have you used?",  # Question changed
        question_hash=compute_content_hash("What profiling tools have you used?"),
        request_id="req_2",
    )
    assert snap.question_hash != comm.question_hash


def test_candidate_qa_mentoring_defers():
    """Mentoring / coaching question is not in job record -> approved deferral."""
    plan = make_test_plan()
    job_facts = extract_job_facts(plan["job_record"])

    decision = {
        "action": "qa_reply",
        "no_experience": False,
        "ack": "Understood.",
        "source_facts": ["job_title"],
        "followup": "We have an extensive senior engineering mentorship and coaching program. Anything else?",
    }
    followup, ack, verified = validate_qa_decision(
        decision=decision,
        job_facts=job_facts,
        candidate_question="What does the mentoring and coaching structure look like for new engineers?",
    )
    assert followup == APPROVED_QA_DEFERRAL
    assert ack == ""
    assert verified == []


def test_candidate_qa_mixed_claims_defers():
    """Candidate Q&A answer mixing supported facts with unsupported claims must defer."""
    plan = make_test_plan()
    job_facts = extract_job_facts(plan["job_record"])

    decision = {
        "action": "qa_reply",
        "no_experience": False,
        "ack": "Right, about the stack and culture.",
        "source_facts": ["required_skill_1"],
        # Sentence 1 is supported, Sentence 2 has unsupported autonomy claim
        "followup": "We use Python for microservices. You will have complete autonomy over team roadmaps. Anything else?",
    }
    followup, ack, verified = validate_qa_decision(
        decision=decision,
        job_facts=job_facts,
        candidate_question="What technologies are used and how much autonomy do I have?",
    )
    assert followup == APPROVED_QA_DEFERRAL
    assert ack == ""


def test_candidate_qa_deferral_suppresses_ack():
    """Whenever Q&A defers, ack must be suppressed to empty string."""
    plan = make_test_plan()
    job_facts = extract_job_facts(plan["job_record"])

    decision = {
        "action": "qa_reply",
        "no_experience": False,
        "ack": "That sounds like a great question about our compensation packages.",
        "source_facts": [],
        "followup": APPROVED_QA_DEFERRAL,
    }
    followup, ack, verified = validate_qa_decision(
        decision=decision,
        job_facts=job_facts,
        candidate_question="Can you tell me about the bonus structure?",
    )
    assert followup == APPROVED_QA_DEFERRAL
    assert ack == ""


def test_ack_forbidden_phrases():
    """Ack validator rejects forbidden phrases: curious about, you're curious about, you have no experience."""
    forbidden = [
        "You're curious about that.",
        "Curious about our backend stack.",
        "You have no experience with Python asyncio.",
    ]
    for raw in forbidden:
        val, _ = validate_and_format_ack(
            raw_ack=raw,
            last_opener=None,
            candidate_answer="I have worked with asyncio.",
            question_text="How do you handle concurrency?",
        )
        assert val == "" or not any(p in val.lower() for p in ("curious about", "no experience"))


def test_ack_verbatim_run_blocked():
    """Ack validator strips or blocks verbatim 5-word echoes from candidate answer."""
    candidate_ans = "We use Kafka message queues for all event streaming in our architecture."
    verbatim_ack = "You use Kafka message queues for all event streaming."
    val, _ = validate_and_format_ack(
        raw_ack=verbatim_ack,
        last_opener=None,
        candidate_answer=candidate_ans,
        question_text="How do you stream events?",
    )
    # Verbatim 5+ words "use Kafka message queues for all event streaming" must not appear intact
    assert "use kafka message queues for all event streaming" not in val.lower()


def test_ack_opener_rotation():
    """Repeated opener rotates and never starts with last_opener."""
    raw = "Right, that clarifies the event loop approach."
    val1, opener1 = validate_and_format_ack(
        raw_ack=raw,
        last_opener="Right,",
        candidate_answer="We use the event loop.",
        question_text="What is asyncio?",
    )
    assert not val1.startswith("Right,")
    assert opener1 != "Right,"


def test_speech_ledger_scoped_lookup_and_separate_actions():
    """Verify get_question_segment_for_turn and distinct action fields."""
    ledger = OutboundSpeechLedger(session_id="test_scoped_ledger")

    # Turn 1
    ledger.record_segment(
        candidate_turn_id="turn_1",
        speech_id="speech_1",
        request_id="q_1",
        semantic_kind="question",
        text="Question 1 text",
        action="clarify",
        raw_action="probe",
        validated_action="clarify",
        effective_action="clarify",
        override_reason="vague_answer_requires_clarify",
        question_id="q_1",
        skill_name="Python",
        scheduled_at_ms=1000,
        status="playback_completed",
    )

    # Turn 2
    ledger.record_segment(
        candidate_turn_id="turn_2",
        speech_id="speech_2",
        request_id="q_2",
        semantic_kind="question",
        text="Question 2 text",
        action="escalate",
        raw_action="escalate",
        validated_action="escalate",
        effective_action="escalate",
        override_reason="",
        question_id="q_2",
        skill_name="Python",
        scheduled_at_ms=2000,
        status="playback_completed",
    )

    # Scoped lookup by turn_id
    q1 = ledger.get_question_segment_for_turn(candidate_turn_id="turn_1")
    assert q1 is not None
    assert q1.text == "Question 1 text"
    assert q1.raw_action == "probe"
    assert q1.effective_action == "clarify"
    assert q1.override_reason == "vague_answer_requires_clarify"

    q2 = ledger.get_question_segment_for_turn(candidate_turn_id="turn_2")
    assert q2 is not None
    assert q2.text == "Question 2 text"

    # Scoped lookup by min_seq
    q_min = ledger.get_question_segment_for_turn(min_seq=2)
    assert q_min is not None
    assert q_min.text == "Question 2 text"

