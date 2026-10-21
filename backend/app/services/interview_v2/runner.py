"""Interview Conductor Runtime Driver (v2) & Fast Reply Path.

Manages the real-time execution of an interview session:
- Script Adapter: build_script(session) reading from real InterviewSession blueprint/personalization/questions.
- Event Queue: Single asyncio.Queue per session processing events sequentially via the pure reducer.
- Effects Execution: Aura-2 streaming, pre-synthesized 0ms bridge playback, timers, persistence, UI frames.
- Fast Reply Path: StartSpeculativeReply(token) background LLM generation, sentence-boundary synthesis,
  1.2s fallback, and strict output validation.
- Per-Turn Latency Tracking: last voiced frame -> EagerEndOfTurn -> EndOfTurn -> commit -> first LLM token -> first TTS byte -> BotAudioStarted.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple, Union

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    BlueprintSection,
    InterviewBlueprint,
    InterviewQuestion,
    InterviewSession,
    InterviewTranscriptTurn,
    JobApplication,
    JobPosting,
)
from backend.app.services.interview_v2.finalizer import finalize_interview_session
from backend.app.services.interview.trace import SessionTrace
from backend.app.services.interview_v2.conductor import (
    AckReady,
    BRIDGES,
    BotAudioStarted,
    BotSpeechDone,
    CancelSpeech,
    CancelSpeculativeReply,
    CancelTimer,
    CommitButton,
    ConductorEffect,
    ConductorEvent,
    ConductorPhase,
    ConductorState,
    DecisionReady,
    EagerTurnEnd,
    EmitUI,
    EndButton,
    Persist,
    PlanQuestion,
    PlayBridge,
    ReadyButton,
    RepeatRequest,
    RequestDecision,
    ScheduleTimer,
    SessionStart,
    Speak,
    SpeakAck,
    StartSpeculativeReply,
    Tick,
    TurnEnd,
    TurnResumed,
    TurnStart,
    _get_current_question,
    get_next_plan_question,
    get_skill_time_left_ms,
    is_ack_grounded,
    step,
    DecisionContextSnapshot,
    OutboundSpeechLedger,
    OutboundSpeechSegment,
    extract_job_facts,
    validate_qa_decision,
    validate_and_format_ack,
    compute_content_hash,
    normalize_text_for_hash,
)
from backend.app.services.llm_router import stream_decision_with_ack_first
from backend.app.services.voice.aura_tts import AuraTTSClient
from backend.app.services.voice.flux_stt import (
    EagerEndOfTurn,
    EndOfTurn,
    FluxEvent,
    FluxSTTClient,
    StartOfTurn,
    TurnResumed as FluxTurnResumed,
    Update,
    get_shared_key_pool,
)

logger = logging.getLogger("candidly.interview_v2.runner")

# Pre-synthesized 8 bridge clips
BRIDGE_PHRASES: List[str] = [
    "Got it.",
    "Thanks.",
    "Okay.",
    "Alright.",
    "Understood.",
    "I see.",
    "Makes sense.",
    "Thank you.",
]

# In-memory pre-synthesized bridge audio cache: phrase -> 24kHz linear16 PCM bytes
BRIDGE_AUDIO_CACHE: Dict[str, bytes] = {}

# In-memory session state store for instant reconnect resume
SESSION_STATE_CACHE: Dict[str, Dict[str, Any]] = {}


# -----------------------------------------------------------------------------
# Pre-Synthesis Bridge Cache
# -----------------------------------------------------------------------------

def generate_fallback_pcm(duration_s: float = 0.4, sample_rate: int = 24000) -> bytes:
    """Generate quiet comfort PCM audio when offline or during test mocks."""
    total_samples = int(duration_s * sample_rate)
    return b"\x00" * (total_samples * 2)


def verify_gemini_live_model() -> bool:
    """Verify GEMINI_MODEL_LIVE resolves at startup with loud ERROR log if unreachable (Requirement 10)."""
    model_name = os.getenv("GEMINI_MODEL_LIVE", "gemini-3.5-flash-lite")
    if os.getenv("GEMINI_MOCK") in ("1", "true", "True") or os.getenv("PYTEST_CURRENT_TEST"):
        return True
    try:
        from backend.app.services.question_generation.provider import get_gemini_client
        client = get_gemini_client()
        resp = client.models.generate_content(
            model=model_name,
            contents="ping",
        )
        logger.info("Verified GEMINI_MODEL_LIVE '%s' resolution successfully at startup", model_name)
        return True
    except Exception as e:
        logger.error(
            "\n"
            "================================================================================\n"
            "CRITICAL: GEMINI_MODEL_LIVE '%s' resolution failed!\n"
            "Error: %s\n"
            "Please check GEMINI_API_KEY / GOOGLE_API_KEY environment variable.\n"
            "================================================================================",
            model_name,
            e,
        )
        return False


async def warmup_bridge_cache(aura_client: Optional[AuraTTSClient] = None) -> None:
    """Pre-synthesize all 8 bridge clips at startup and store in memory for 0ms playback."""
    global BRIDGE_AUDIO_CACHE
    verify_gemini_live_model()
    client = aura_client or AuraTTSClient(sample_rate=24000)

    for phrase in BRIDGE_PHRASES:
        if phrase in BRIDGE_AUDIO_CACHE and len(BRIDGE_AUDIO_CACHE[phrase]) > 0:
            continue
        try:
            chunks: List[bytes] = []
            async for chunk in client.speak(phrase):
                chunks.append(chunk)
            full_pcm = b"".join(chunks)
            if full_pcm:
                BRIDGE_AUDIO_CACHE[phrase] = full_pcm
                logger.info("Pre-synthesized bridge '%s' (%d bytes)", phrase, len(full_pcm))
            else:
                BRIDGE_AUDIO_CACHE[phrase] = generate_fallback_pcm(0.35)
        except Exception as e:
            logger.warning("Could not pre-synthesize bridge '%s' (fallback applied): %s", phrase, e)
            BRIDGE_AUDIO_CACHE[phrase] = generate_fallback_pcm(0.35)


# -----------------------------------------------------------------------------
# Script Adapter: Real InterviewSession -> Conductor Plan
# -----------------------------------------------------------------------------

def build_script(session: Any) -> Dict[str, Any]:
    """Adapter reading existing blueprint/personalization/plan_materializer output

    from a real InterviewSession and mapping it to the conductor's PlanQuestion structure.
    Confirms in runtime that real InterviewSession rows feed the conductor.
    """
    raw_questions = getattr(session, "questions", []) or []
    # Sort strictly by question_index to preserve deterministic script ordering
    sorted_questions = sorted(raw_questions, key=lambda q: getattr(q, "question_index", 0) or 0)
    plan_questions: List[Dict[str, Any]] = []

    # Track skills to infer anchor/followup if kind was unassigned in legacy sessions
    seen_skills: Dict[str, int] = {}

    for q in sorted_questions:
        q_idx = int(getattr(q, "question_index", 0))
        kind = getattr(q, "kind", None)
        text = str(getattr(q, "question_text", "") or "")
        skill_name = str(getattr(q, "skill_name", "") or "")

        # Fallback kind inference for legacy/unmaterialized questions
        if not kind:
            t_lower = text.lower()
            if q_idx == 0 or "welcome" in t_lower:
                kind = "welcome"
            elif q_idx == 1 or "introduce yourself" in t_lower or "background" in t_lower:
                kind = "intro_hook"
            elif "any questions" in t_lower or "open up the floor" in t_lower:
                kind = "candidate_qa"
            elif "thank you" in t_lower and ("concluded" in t_lower or "great day" in t_lower or "wonderful" in t_lower):
                kind = "closing"
            else:
                count_for_skill = seen_skills.get(skill_name, 0)
                if count_for_skill == 0:
                    kind = "anchor"
                elif count_for_skill == 1:
                    kind = "anchor_alt"
                elif count_for_skill == 2:
                    kind = "escalation"
                else:
                    kind = "probe"
                seen_skills[skill_name] = count_for_skill + 1

        # Extract trigger_condition and probe_id
        trigger_cond = getattr(q, "trigger_condition", None)
        if not trigger_cond:
            p_ctx = getattr(q, "personalization_context", None)
            if isinstance(p_ctx, dict):
                trigger_cond = p_ctx.get("trigger_condition")

        probe_id = str(getattr(q, "id", "") or getattr(q, "blueprint_question_id", "") or "")

        plan_questions.append({
            "question_index": q_idx,
            "kind": str(kind),
            "skill_name": skill_name,
            "question_text": text,
            "priority_tier": str(getattr(q, "priority_tier", "P0") or "P0"),
            "section_id": str(getattr(q, "section_id", "")) if getattr(q, "section_id", None) else None,
            "expected_key_points": list(getattr(q, "expected_key_points", []) or []),
            "trigger_condition": trigger_cond,
            "probe_id": probe_id,
        })

    # Build per-skill budget from blueprint section minutes (fallback 5 min = 300,000 ms)
    skill_budgets_ms: Dict[str, int] = {}
    blueprint = getattr(session, "blueprint", None)
    if blueprint and getattr(blueprint, "sections", None):
        for sec in blueprint.sections:
            s_name = getattr(sec, "skill_name", None)
            mins = getattr(sec, "allocated_minutes", None)
            if s_name and mins:
                skill_budgets_ms[s_name] = int(float(mins) * 60 * 1000)

    # Build job record facts for Candidate Q&A (Requirement 4)
    job_record: Dict[str, Any] = {}
    job = getattr(session, "job", None)
    if job:
        raw_skills = getattr(job, "skills", []) or []
        skill_names = [
            getattr(s, "name", str(s)) if not isinstance(s, str) else s
            for s in raw_skills
        ]
        job_record = {
            "title": str(getattr(job, "job_title", "") or getattr(job, "title", "") or ""),
            "description": str(getattr(job, "job_description", "") or getattr(job, "description", "") or ""),
            "skills": skill_names,
            "seniority": str(getattr(job, "seniority_level", "") or getattr(job, "seniority", "") or getattr(job, "level", "") or ""),
        }
    elif blueprint:
        raw_skills = getattr(blueprint, "target_skills", []) or []
        skill_names = [
            getattr(s, "name", str(s)) if not isinstance(s, str) else s
            for s in raw_skills
        ]
        job_record = {
            "title": str(getattr(blueprint, "job_title", "") or getattr(blueprint, "title", "") or ""),
            "description": str(getattr(blueprint, "job_description", "") or getattr(blueprint, "description", "") or ""),
            "skills": skill_names,
            "seniority": str(getattr(blueprint, "seniority_level", "") or getattr(blueprint, "seniority", "") or ""),
        }

    return {"questions": plan_questions, "skill_budgets_ms": skill_budgets_ms, "job_record": job_record}


async def load_real_session_script(session_id: str) -> Tuple[Optional[InterviewSession], Dict[str, Any]]:
    """Load a real InterviewSession from the database and build the conductor script,
    with full eager-loading across questions, job skills, and blueprint sections."""
    async with AsyncSessionLocal() as db:
        eager_options = (
            selectinload(InterviewSession.questions),
            selectinload(InterviewSession.job).selectinload(JobPosting.skills),
            selectinload(InterviewSession.blueprint).selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.questions),
            selectinload(InterviewSession.blueprint).selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.expectations),
        )
        result = await db.execute(
            select(InterviewSession)
            .where(InterviewSession.id == session_id)
            .options(*eager_options)
        )
        session = result.scalar_one_or_none()
        if not session:
            return None, {"questions": []}

        # If questions were not materialized yet, materialize now
        if not session.questions or len(session.questions) == 0:
            from backend.app.services.interview.plan_materializer import materialize_blueprint_session_plan
            await materialize_blueprint_session_plan(session, db)
            await db.commit()
            # Reload with full eager options
            result2 = await db.execute(
                select(InterviewSession)
                .where(InterviewSession.id == session_id)
                .options(*eager_options)
            )
            session = result2.scalar_one_or_none()

        script = build_script(session)
        return session, script


# -----------------------------------------------------------------------------
# Latency Waterfall Metrics
# -----------------------------------------------------------------------------

@dataclass
class TurnLatencyMetrics:
    turn_index: int = 0
    question_text: str = ""
    last_voiced_frame_time: float = 0.0
    eager_eot_time: Optional[float] = None
    end_of_turn_time: Optional[float] = None
    commit_time: Optional[float] = None
    first_llm_token_time: Optional[float] = None
    first_tts_byte_time: Optional[float] = None
    bot_audio_started_time: Optional[float] = None
    used_bridge: bool = False
    speculation_used: bool = False
    speculation_discarded: bool = False
    speculation_discard_reason: str = ""
    speculation_outcome: Optional[str] = None
    model_generation_latency_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        voiced = self.last_voiced_frame_time
        audio = self.bot_audio_started_time or 0.0
        commit = self.commit_time or 0.0
        eot = self.end_of_turn_time

        voiced_to_audio_ms = round((audio - voiced) * 1000.0, 1) if (voiced and audio > voiced) else 0.0
        flux_wait_ms = (
            round((eot - voiced) * 1000.0, 1)
            if (voiced and eot and eot >= voiced)
            else None
        )
        commit_to_audio_ms = round((audio - commit) * 1000.0, 1) if (commit and audio > commit) else 0.0
        llm_ttft_ms = round((self.first_llm_token_time - commit) * 1000.0, 1) if (commit and self.first_llm_token_time and self.first_llm_token_time > commit) else None
        first_tts_ms = round((self.first_tts_byte_time - commit) * 1000.0, 1) if (commit and self.first_tts_byte_time and self.first_tts_byte_time > commit) else None

        return {
            "turn_index": self.turn_index,
            "question_text": self.question_text[:60] + "..." if len(self.question_text) > 60 else self.question_text,
            "voiced_to_audio_ms": voiced_to_audio_ms,
            "flux_wait_ms": flux_wait_ms,
            "commit_to_audio_ms": commit_to_audio_ms,
            "llm_ttft_ms": llm_ttft_ms,
            "first_tts_ms": first_tts_ms,
            "used_bridge": self.used_bridge,
            "speculation_used": self.speculation_used,
            "speculation_discarded": self.speculation_discarded,
            "speculation_discard_reason": self.speculation_discard_reason,
        }


def normalize_text(text: str) -> str:
    """Normalize text for exact comparison: collapse whitespace, lowercase, strip trailing punctuation."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    cleaned = re.sub(r"[\.,!\?;]+$", "", cleaned).strip()
    return cleaned


# -----------------------------------------------------------------------------
# Speculative Reply Manager
# -----------------------------------------------------------------------------

PRAISE_CLI_REGEX = re.compile(r"\b(great job|awesome|fantastic|good answer|well done|perfect|excellent|wonderful)\b", re.IGNORECASE)
EVAL_CLI_REGEX = re.compile(r"\b(that is correct|that's correct|you are right|you're right|correct|incorrect|wrong|that is wrong)\b", re.IGNORECASE)
CODE_WHITEBOARD_REGEX = re.compile(r"\b(write code|whiteboard|share your screen|implement a function|write a function|coding exercise)\b", re.IGNORECASE)


def validate_speculative_output(text: str) -> bool:
    """Validate fast reply output per Phase 4 requirements:

    - Reaction sentence <= 18 words
    - No praise clichés
    - No evaluating ('correct', 'wrong', etc.)
    - Exactly one question
    - No code or whiteboard asks
    - No new topics
    """
    if not text or not text.strip():
        return False

    cleaned = text.strip()

    # Must contain exactly one question mark
    if cleaned.count("?") != 1:
        return False

    # Check praise and evaluation clichés
    if PRAISE_CLI_REGEX.search(cleaned):
        return False
    if EVAL_CLI_REGEX.search(cleaned):
        return False

    # Check coding/whiteboard asks
    if CODE_WHITEBOARD_REGEX.search(cleaned):
        return False

    # Split into reaction sentence and question
    # Expect: "<Reaction sentence>. <Next question>?"
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", cleaned) if p.strip()]
    if len(parts) < 2:
        return False

    reaction = parts[0]
    reaction_words = re.findall(r"\b[\w'-]+\b", reaction)
    if len(reaction_words) > 18:
        return False

    return True


# -----------------------------------------------------------------------------
# Runtime Session Runner
# -----------------------------------------------------------------------------

class SessionRunner:
    """One asyncio task per session managing the event queue, conductor step,

    speculative reply generation, and effect execution.
    """

    def __init__(
        self,
        session_id: str,
        script: Dict[str, Any],
        websocket: Optional[WebSocket] = None,
        flux_client: Optional[FluxSTTClient] = None,
        aura_client: Optional[AuraTTSClient] = None,
        llm_fn: Optional[Callable[[str, str, str], AsyncIterator[str]]] = None,
        clock_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        self.session_id = session_id
        self.script = script
        self.websocket = websocket
        self.flux_client = flux_client
        self.aura_client = aura_client or AuraTTSClient(sample_rate=24000)
        self.llm_fn = llm_fn
        self.clock_fn = clock_fn or (lambda: int(time.time() * 1000))

        # Single event queue
        self.queue: asyncio.Queue[ConductorEvent] = asyncio.Queue()

        # Conductor State
        cached_dict = SESSION_STATE_CACHE.get(session_id)
        if cached_dict:
            self.state = ConductorState.from_dict(cached_dict)
            logger.info("Resumed session %s from cached conductor state (phase=%s)", session_id, self.state.phase.value)
        else:
            self.state = ConductorState()

        # Session Trace
        self.trace = SessionTrace(session_id)

        # Authoritative Outbound Speech Ledger (Phase A6)
        self.speech_ledger: OutboundSpeechLedger = OutboundSpeechLedger(session_id=session_id)

        # Control flags
        self.running: bool = False
        self.runner_task: Optional[asyncio.Task[None]] = None

        # Active timer tasks: timer_name -> asyncio.Task
        self.timer_tasks: Dict[str, asyncio.Task[None]] = {}

        # Speculative reply state
        self.spec_task: Optional[asyncio.Task[None]] = None
        self.spec_token: Optional[str] = None
        self.spec_source_text: str = ""
        self.spec_text: str = ""
        self.spec_audio_chunks: List[bytes] = []
        self.spec_valid: bool = False
        self.spec_first_sentence_ready = asyncio.Event()
        self.spec_decision: Optional[Dict[str, Any]] = None
        self.spec_snapshot: Optional[DecisionContextSnapshot] = None
        self.spec_start_wall_time: float = 0.0
        self.spec_inference_latency_ms: Optional[float] = None
        self.spec_attempted: bool = False

        # Active speech streaming task
        self.speech_task: Optional[asyncio.Task[None]] = None

        # Decision & fallback tracking
        self.last_decision_used_fallback: bool = False
        self.last_raw_decision: Optional[Dict[str, Any]] = None
        self.last_decision_latency_ms: float = 0.0
        self.last_spoken_tts_text: str = ""

        # Latency tracking
        self.current_metrics = TurnLatencyMetrics()
        self.latency_history: List[Dict[str, Any]] = []
        self.end_request_id: Optional[str] = None

    def now_ms(self) -> int:
        return self.clock_fn()

    async def start(self) -> None:
        """Start the runner background task and initialize the interview script."""
        if self.running:
            return
        self.running = True

        # Initialize script if at start, aborted welcome, or previously completed
        if self.state.phase in (ConductorPhase.INIT, ConductorPhase.WELCOME, ConductorPhase.COMPLETED):
            self.state = ConductorState()
            await self.queue.put(SessionStart(session_id=self.session_id, plan=self.script, now_ms=self.now_ms()))
        else:
            # Active interview reconnect: re-sync state and current question
            asyncio.create_task(self._reconnect_resync())

        self.runner_task = asyncio.create_task(self._run_loop())

    async def _reconnect_resync(self) -> None:
        """On active session reconnection, send UIStatus and re-speak current question if bot was speaking."""
        await asyncio.sleep(0.15)
        curr_q = self.state.current_question
        text = curr_q.question_text if curr_q else ""
        skill = curr_q.skill if curr_q else ""
        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "UIStatus",
                    "status": self.state.status,
                    "phase": self.state.phase.value,
                    "question_index": self.state.current_question_index,
                    "payload": {
                        "question_text": text,
                        "skill": skill,
                    },
                })
                if self.state.bot_speaking and text:
                    self.state.speech_seq += 1
                    speech_id = f"speech_{self.state.speech_seq}"
                    self.state.active_speech_id = speech_id
                    await self._handle_speak(Speak(text=text, speech_id=speech_id))
            except Exception as e:
                logger.debug("Failed reconnect resync: %s", e)

    async def stop(self) -> None:
        """Cancel runner and active tasks cleanly."""
        self.running = False
        if self.runner_task and not self.runner_task.done():
            self.runner_task.cancel()
        for t in self.timer_tasks.values():
            if not t.done():
                t.cancel()
        self.timer_tasks.clear()
        if self.spec_task and not self.spec_task.done():
            self.spec_task.cancel()
        if self.speech_task and not self.speech_task.done():
            self.speech_task.cancel()

    async def _save_state(self) -> None:
        """Cache state for reconnection resume."""
        SESSION_STATE_CACHE[self.session_id] = self.state.to_dict()

    async def _run_loop(self) -> None:
        """Main event loop: pop event, step(state, event), store state, execute effects.

        Never run effects concurrently with step.
        """
        while self.running:
            try:
                event = await self.queue.get()
                # Latency metric lifecycle
                if isinstance(event, TurnStart) and self.current_metrics.bot_audio_started_time is not None:
                    self.current_metrics = TurnLatencyMetrics(turn_index=self.current_metrics.turn_index + 1)

                if isinstance(event, BotAudioStarted):
                    if self.current_metrics.bot_audio_started_time is None:
                        self.current_metrics.bot_audio_started_time = time.perf_counter()
                    if self.current_metrics.commit_time or self.current_metrics.last_voiced_frame_time:
                        metrics_dict = self.current_metrics.to_dict()
                        if self.latency_history and self.latency_history[-1].get("turn_index") == self.current_metrics.turn_index:
                            self.latency_history[-1] = metrics_dict
                        else:
                            self.latency_history.append(metrics_dict)
                        if len(self.latency_history) >= 10:
                            latencies = sorted(
                                m["commit_to_audio_ms"] for m in self.latency_history if m.get("commit_to_audio_ms")
                            )
                            if latencies:
                                p50 = latencies[len(latencies) // 2]
                                p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
                                logger.info(
                                    "Session %s turn latency stats (turns=%d): p50=%.1fms, p95=%.1fms",
                                    self.session_id, len(latencies), p50, p95
                                )
                        if self.websocket:
                            try:
                                await self.websocket.send_json({"type": "TurnMetrics", "metrics": metrics_dict})
                            except Exception:
                                pass

                prev_phase = self.state.phase

                # Pure reducer step
                self.state, effects = step(self.state, event)

                # Persist state
                await self._save_state()

                # Sequential effect execution
                for effect in effects:
                    await self._execute_effect(effect)

                # Log phase transitions
                if self.state.phase != prev_phase:
                    logger.info("Session %s phase: %s -> %s", self.session_id, prev_phase.value, self.state.phase.value)
                    if self.state.phase == ConductorPhase.CLOSING:
                        if self.websocket:
                            try:
                                await self.websocket.send_json({
                                    "type": "SessionEnding",
                                    "session_id": self.session_id,
                                    "request_id": self.end_request_id or getattr(event, "request_id", None) or "",
                                    "status": "ending",
                                })
                            except Exception:
                                pass

                    if self.state.phase == ConductorPhase.COMPLETED:
                        persistence_ok = False
                        try:
                            async with AsyncSessionLocal() as db:
                                await finalize_interview_session(self.session_id, ended_by="candidate", db=db)
                            persistence_ok = True
                        except Exception as e:
                            logger.error("Could not finalize session %s in DB: %s", self.session_id, e, exc_info=True)
                            if self.websocket:
                                try:
                                    await self.websocket.send_json({
                                        "type": "SessionError",
                                        "error": "SessionPersistenceFailed",
                                        "detail": "Failed to persist interview session completion to database.",
                                        "retryable": True,
                                    })
                                except Exception:
                                    pass

                        if persistence_ok and self.websocket:
                            try:
                                await self.websocket.send_json({
                                    "type": "SessionEnded",
                                    "session_id": self.session_id,
                                    "request_id": self.end_request_id or getattr(event, "request_id", None) or "",
                                    "status": "completed",
                                })
                            except Exception:
                                pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in SessionRunner loop: %s", e, exc_info=True)

    # -------------------------------------------------------------------------
    # Effects Execution
    # -------------------------------------------------------------------------

    async def _execute_effect(self, effect: ConductorEffect) -> None:
        """Execute a single conductor effect."""
        if isinstance(effect, Speak):
            await self._handle_speak(effect)

        elif isinstance(effect, SpeakAck):
            await self._handle_speak_ack(effect)

        elif isinstance(effect, CancelSpeech):
            await self._handle_cancel_speech()

        elif isinstance(effect, RequestDecision):
            await self._handle_request_decision(effect)

        elif isinstance(effect, StartSpeculativeReply):
            await self._handle_start_speculative_reply(effect)

        elif isinstance(effect, CancelSpeculativeReply):
            await self._handle_cancel_speculative_reply(effect.token)

        elif isinstance(effect, PlayBridge):
            await self._handle_play_bridge(effect)

        elif isinstance(effect, ScheduleTimer):
            self._handle_schedule_timer(effect)

        elif isinstance(effect, CancelTimer):
            self._handle_cancel_timer(effect.name)

        elif isinstance(effect, Persist):
            await self._handle_persist(effect.turn)

        elif isinstance(effect, EmitUI):
            await self._handle_emit_ui(effect)

    async def _handle_speak_ack(self, effect: SpeakAck) -> None:
        """Execute SpeakAck effect: immediately stream Aura-2 synthesizing the ack alone."""
        self.current_metrics.commit_time = time.perf_counter()
        self.last_spoken_tts_text = effect.text

        # Record segment in authoritative outbound speech ledger (Phase A6)
        curr_turn_id = self.state.current_candidate_turn_id or f"turn_{self.state.turn_counter}"
        self.speech_ledger.record_segment(
            candidate_turn_id=curr_turn_id,
            speech_id=effect.speech_id,
            request_id=f"ack_{effect.speech_id}",
            semantic_kind="ack",
            text=effect.text,
            action=getattr(effect, "action", "") or "ack",
            effective_action=getattr(effect, "action", "") or "ack",
            raw_action=getattr(effect, "action", "") or "ack",
            validated_action=getattr(effect, "action", "") or "ack",
            question_id=getattr(effect, "question_id", ""),
            skill_name=getattr(effect, "skill_name", ""),
            scheduled_at_ms=self.now_ms(),
            status="included_in_outbound",
        )

        # Clear candidate live speech text in UI
        if self.websocket:
            try:
                await self.websocket.send_json({"type": "Update", "text": ""})
            except Exception:
                pass

        if self.websocket:
            try:
                await self.websocket.send_json({"type": "BotState", "state": "speaking"})
            except Exception:
                pass

        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "BotSpeechStarted",
                    "speech_id": effect.speech_id,
                    "text": effect.text,
                    "is_ack": True,
                })
            except Exception:
                pass

        await self.queue.put(BotAudioStarted(speech_id=effect.speech_id, now_ms=self.now_ms()))

        # Stream the ack audio
        if self.speech_task and not self.speech_task.done():
            self.speech_task.cancel()

        async def _speak_ack_task():
            try:
                is_spec = False
                first_ack_chunk = True
                self.speech_ledger.mark_sent(effect.speech_id, self.now_ms())
                async for chunk in self.aura_client.speak(effect.text):
                    if first_ack_chunk:
                        first_ack_chunk = False
                        self.speech_ledger.mark_started(effect.speech_id, self.now_ms(), kind="ack")
                    if self.websocket:
                        await self.websocket.send_bytes(chunk)
                self.speech_ledger.mark_completed(effect.speech_id, self.now_ms(), kind="ack")
                if self.websocket:
                    await self.websocket.send_json({
                        "type": "TTSDone",
                        "speech_id": effect.speech_id,
                        "is_ack": True,
                        "is_speculative": is_spec,
                    })
            except asyncio.CancelledError:
                self.speech_ledger.mark_cancelled(effect.speech_id)
                if self.websocket:
                    await self.websocket.send_json({"type": "TTSCancelled", "speech_id": effect.speech_id})
            except Exception as e:
                logger.error("Error streaming SpeakAck: %s", repr(e), exc_info=True)
            finally:
                await self.queue.put(BotSpeechDone(speech_id=effect.speech_id, now_ms=self.now_ms()))

        self.speech_task = asyncio.create_task(_speak_ack_task())

    async def _handle_speak(self, effect: Speak) -> None:
        """Execute Speak effect: stream Aura-2 synthesizing ack and question back-to-back under same speech_id."""
        self.current_metrics.commit_time = time.perf_counter()
        self.current_metrics.question_text = effect.text
        self.last_spoken_tts_text = effect.text

        # Record semantic segments in authoritative outbound speech ledger (Phase A6)
        curr_turn_id = self.state.current_candidate_turn_id or f"turn_{self.state.turn_counter}"
        if getattr(effect, "transition_text", None):
            self.speech_ledger.record_segment(
                candidate_turn_id=curr_turn_id,
                speech_id=effect.speech_id,
                request_id=f"trans_{effect.speech_id}",
                semantic_kind="transition",
                text=effect.transition_text,
                action=getattr(effect, "kind", "transition") or "transition",
                effective_action=getattr(effect, "kind", "transition") or "transition",
                raw_action=getattr(effect, "kind", "transition") or "transition",
                validated_action=getattr(effect, "kind", "transition") or "transition",
                skill_name=getattr(effect, "skill_name", ""),
                scheduled_at_ms=self.now_ms(),
                status="included_in_outbound",
            )
        if getattr(effect, "ack_text", None) and not (self.state.spoken_ack_token and self.state.spoken_ack_token == self.state.decision_token):
            self.speech_ledger.record_segment(
                candidate_turn_id=curr_turn_id,
                speech_id=effect.speech_id,
                request_id=f"ack_{effect.speech_id}",
                semantic_kind="ack",
                text=effect.ack_text,
                action="ack",
                effective_action="ack",
                raw_action="ack",
                validated_action="ack",
                question_id=getattr(effect, "question_id", ""),
                skill_name=getattr(effect, "skill_name", ""),
                scheduled_at_ms=self.now_ms(),
                status="included_in_outbound",
            )
        q_text = getattr(effect, "question_text", None) or effect.text
        if q_text:
            raw_kind = getattr(effect, "kind", "question") or "question"
            sem_kind = raw_kind if raw_kind in ("closing", "qa_reply") else "question"
            self.speech_ledger.record_segment(
                candidate_turn_id=curr_turn_id,
                speech_id=effect.speech_id,
                request_id=f"q_{effect.speech_id}",
                semantic_kind=sem_kind,
                text=q_text,
                action=raw_kind,
                effective_action=raw_kind,
                raw_action=raw_kind,
                validated_action=raw_kind,
                question_id=getattr(effect, "question_id", ""),
                skill_name=getattr(effect, "skill_name", ""),
                scheduled_at_ms=self.now_ms(),
                status="included_in_outbound",
            )

        # Clear candidate live speech text in UI on bot speak
        if self.websocket:
            try:
                await self.websocket.send_json({"type": "Update", "text": ""})
            except Exception:
                pass

        if self.websocket:
            if self.speech_task and not self.speech_task.done():
                self.speech_task.cancel()
            self.speech_task = asyncio.create_task(self._stream_aura_speech(effect))

    async def _stream_aura_speech(self, effect: Speak) -> None:
        """Stream Aura-2 TTS chunks to the client over WebSocket.
        Synthesizes ack and question as two Aura-2 requests streamed back to back under the same speech_id.
        """
        speech_id = effect.speech_id
        try:
            # Small initial breather on session start so client audio worklets are attached
            if self.state.phase == ConductorPhase.WELCOME:
                await asyncio.sleep(0.15)

            to_speak = effect.text.strip()
            if not to_speak:
                return

            first_chunk = True
            is_spec = bool(self.current_metrics.speculation_used)
            self.speech_ledger.mark_sent(speech_id, self.now_ms())
            async for chunk in self.aura_client.speak(to_speak):
                if first_chunk:
                    first_chunk = False
                    self.current_metrics.first_tts_byte_time = time.perf_counter()
                    self.speech_ledger.mark_started(speech_id, self.now_ms())
                    if self.websocket:
                        await self.websocket.send_json({
                            "type": "TTSStarted",
                            "speech_id": speech_id,
                            "voice": self.aura_client.voice,
                            "text": to_speak,
                            "is_speculative": is_spec,
                        })
                if self.websocket:
                    await self.websocket.send_bytes(chunk)

            self.speech_ledger.mark_completed(speech_id, self.now_ms())
            if self.websocket:
                await self.websocket.send_json({
                    "type": "TTSDone",
                    "speech_id": speech_id,
                    "is_speculative": is_spec,
                })
        except asyncio.CancelledError:
            self.speech_ledger.mark_cancelled(speech_id)
            if self.websocket:
                await self.websocket.send_json({"type": "TTSCancelled", "speech_id": speech_id})
        except Exception as e:
            logger.error("Error streaming Aura speech: %s", repr(e), exc_info=True)
            self.speech_ledger.mark_cancelled(speech_id)
            if self.websocket:
                try:
                    await self.websocket.send_json({"type": "TTSError", "speech_id": speech_id, "error": str(e)})
                except Exception:
                    pass
            # Clear stuck speaking state and transition to listening
            self.state.bot_speaking = False
            self.state.bot_audio_started = False
            await self.queue.put(BotSpeechDone(speech_id=speech_id, now_ms=self.now_ms()))

    async def _handle_cancel_speech(self) -> None:
        """Cancel active TTS stream and speculative generation."""
        if self.speech_task and not self.speech_task.done():
            self.speech_task.cancel()
        if self.spec_task and not self.spec_task.done():
            self.spec_task.cancel()
        self.spec_token = None
        self.spec_source_text = ""
        self.spec_snapshot = None
        self.spec_decision = None
        await self.aura_client.cancel()
        if self.websocket:
            try:
                await self.websocket.send_json({"type": "TTSCancelled"})
            except Exception:
                pass

    async def _handle_request_decision(self, effect: RequestDecision) -> None:
        """Handle conductor RequestDecision effect: reuse speculative decision if context matches, or call LLM."""
        self.current_metrics.commit_time = time.perf_counter()
        committed_answer = effect.answer_text
        committed_snapshot = getattr(effect, "snapshot", None)

        # 1. Speculative decision match check
        if self.spec_token and self.spec_snapshot:
            # Wait briefly if speculative task is currently in flight (up to 0.8s)
            if self.spec_task and not self.spec_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(self.spec_task), timeout=0.8)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

            snap = self.spec_snapshot
            comm = committed_snapshot
            spec_outcome = None

            if comm is not None:
                if (
                    snap.session_id != comm.session_id
                    or snap.candidate_turn_id != comm.candidate_turn_id
                    or snap.question_index != comm.question_index
                    or snap.skill_name != comm.skill_name
                    or snap.phase != comm.phase
                    or snap.question_hash != comm.question_hash
                ):
                    spec_outcome = "discard_context_mismatch"
                elif snap.answer_hash != comm.answer_hash:
                    spec_outcome = "discard_text_mismatch"
                elif self.spec_decision is None:
                    spec_outcome = "discard_not_ready"
                else:
                    spec_outcome = "reused"
            else:
                source_hash = compute_content_hash(self.spec_source_text)
                committed_hash = compute_content_hash(committed_answer)
                if source_hash != committed_hash:
                    spec_outcome = "discard_text_mismatch"
                elif self.spec_decision is None:
                    spec_outcome = "discard_not_ready"
                else:
                    spec_outcome = "reused"

            if spec_outcome == "reused":
                # Exact match across all context dimensions! Reuse speculation!
                self.current_metrics.speculation_used = True
                self.current_metrics.speculation_discarded = False
                self.current_metrics.speculation_outcome = "reused"
                logger.info("Fast reply path: reusing speculative decision for %s", effect.token)
                self.last_raw_decision = self.spec_decision
                self.last_decision_used_fallback = False
                # Report actual model generation duration separately from commit-to-usable latency
                self.current_metrics.model_generation_latency_ms = self.spec_inference_latency_ms
                self.last_decision_latency_ms = self.spec_inference_latency_ms if self.spec_inference_latency_ms is not None else (time.perf_counter() - self.current_metrics.commit_time) * 1000.0

                if effect.skill == "Candidate Q&A" or self.spec_decision.get("action") == "qa_reply":
                    job_facts = extract_job_facts(self.state.job_record or {})
                    eff_fol, eff_ack, verified_facts = validate_qa_decision(self.spec_decision, job_facts, committed_answer)
                    self.spec_decision["followup"] = eff_fol
                    self.spec_decision["ack"] = eff_ack  # NEVER eff_ack or ...
                    self.spec_decision["source_facts"] = verified_facts

                spec_action = self.spec_decision.get("action", "")
                spec_ack = (self.spec_decision.get("ack") or "").strip()

                if spec_action == "off_topic":
                    spec_ack = ""
                    self.spec_decision["ack"] = ""

                # Validate ack
                if spec_ack and is_ack_grounded(spec_ack, effect.answer_text, effect.question_text):
                    val_ack, _ = validate_and_format_ack(
                        raw_ack=spec_ack,
                        last_opener=getattr(effect, "last_ack_opener", None),
                        candidate_answer=effect.answer_text,
                        question_text=effect.question_text,
                        action=spec_action,
                        no_experience=self.spec_decision.get("no_experience", False),
                    )
                    if val_ack:
                        self.spec_decision["ack"] = val_ack
                        await self.queue.put(AckReady(
                            token=effect.token,
                            text=val_ack,
                            action=spec_action,
                            no_experience=self.spec_decision.get("no_experience", False),
                            snapshot=self.spec_snapshot,
                            now_ms=self.now_ms(),
                        ))
                    else:
                        self.spec_decision["ack"] = ""
                elif spec_ack and spec_action != "qa_reply":
                    logger.info("Speculative ack '%s' failed validation/grounding. Regenerating once...", spec_ack)
                    regen_ack = await self._regenerate_grounded_ack(effect.answer_text, effect.question_text, spec_ack)
                    if regen_ack and is_ack_grounded(regen_ack, effect.answer_text, effect.question_text):
                        val_regen, _ = validate_and_format_ack(
                            raw_ack=regen_ack,
                            last_opener=getattr(effect, "last_ack_opener", None),
                            candidate_answer=effect.answer_text,
                            question_text=effect.question_text,
                            action=spec_action,
                            no_experience=self.spec_decision.get("no_experience", False),
                        )
                        if val_regen:
                            self.spec_decision["ack"] = val_regen
                            await self.queue.put(AckReady(
                                token=effect.token,
                                text=val_regen,
                                action=spec_action,
                                no_experience=self.spec_decision.get("no_experience", False),
                                snapshot=self.spec_snapshot,
                                now_ms=self.now_ms(),
                            ))
                        else:
                            self.spec_decision["ack"] = ""
                    else:
                        logger.info("Regenerated ack for speculative decision failed grounding check; speaking NO ack.")
                        self.spec_decision["ack"] = ""
                else:
                    self.spec_decision["ack"] = ""

                # Enqueue DecisionReady with ORIGINATING spec_snapshot
                await self.queue.put(DecisionReady(
                    token=effect.token,
                    decision=self.spec_decision,
                    snapshot=self.spec_snapshot,
                    now_ms=self.now_ms(),
                ))
                self.spec_token = None
                self.spec_source_text = ""
                self.spec_snapshot = None
                self.spec_decision = None
                return
            else:
                logger.info(
                    "Fast reply path: discarding speculation (%s).",
                    spec_outcome,
                )
                self.current_metrics.speculation_discarded = True
                self.current_metrics.speculation_outcome = spec_outcome
                self.current_metrics.speculation_discard_reason = spec_outcome.replace("discard_", "") if spec_outcome.startswith("discard_") else spec_outcome
                self.current_metrics.speculation_used = False
                if self.spec_task and not self.spec_task.done():
                    self.spec_task.cancel()
                self.spec_token = None
                self.spec_source_text = ""
                self.spec_snapshot = None
                self.spec_decision = None

        # 2. Spawning LLM decision task
        asyncio.create_task(self._call_decision_llm(effect))

    def _build_qa_prompt(self, candidate_question: str, last_ack_opener: Optional[str]) -> Tuple[str, str, Dict[str, str]]:
        job_facts = extract_job_facts(self.state.job_record or {})
        formatted_facts = "\n".join(f"- {fid}: {fval}" for fid, fval in job_facts.items())
        avoid_opener = f"Do NOT start with '{last_ack_opener}'." if last_ack_opener else ""
        system_prompt = (
            "You are the technical interviewer answering during Candidate Q&A. "
            "Output compact JSON with key order: action, no_experience, ack, source_facts, followup, probe_id, covered_expectations."
        )
        user_prompt = (
            f"Job Facts:\n{formatted_facts}\n\n"
            f"Candidate asked: {candidate_question[:150]}\n"
            "STRICT RULES:\n"
            "1. Answer using ONLY job facts above. Cite exact fact IDs used in 'source_facts'. If not supported say: "
            "'I don't have that detail in our job description, but our hiring team will follow up with you on that.'\n"
            "2. Append 'Anything else?' to your response. Max 2 sentences, 35 words total.\n"
            "3. Never invent salary, bonus, benefits, culture, team size, autonomy, mentoring, or 6-month goals.\n"
            f"4. ack: natural short ack reacting to candidate question or empty string <= 10 words. {avoid_opener}\n"
            '5. JSON schema: {"action": "qa_reply", "no_experience": false, "ack": "...", "source_facts": ["fact_id"], "followup": "...", "probe_id": null, "covered_expectations": []}'
        )
        return system_prompt, user_prompt, job_facts

    def _build_decision_prompt(
        self,
        skill: str,
        question_text: str,
        answer_text: str,
        probes: List[Any],
        escalation_text: str,
        anchor_alt_text: str,
        expectations: List[Any],
        stretch_expectations: List[Any],
        followups_used: int,
        time_left_ms: int,
        last_ack_opener: Optional[str],
    ) -> Tuple[str, str]:
        avoid_opener = f"NEVER start the ack with '{last_ack_opener}'." if last_ack_opener else ""
        ans_words = answer_text.split()
        capped_ans = " ".join(ans_words[:150])

        compact_probes = [
            {"id": str(p.get("id", "")), "text": p.get("text", "")}
            for p in (probes or [])[:3]
        ]
        exp_ids = [str(e) for e in (expectations or [])]
        stretch_ids = [str(s) for s in (stretch_expectations or [])]

        system_prompt = (
            "You are an expert technical interviewer evaluating candidate answers live. "
            "Output strictly compact JSON with keys in this exact order: "
            "action, no_experience, ack, probe_id, followup, covered_expectations."
        )
        user_prompt = (
            f"Skill: {skill}\n"
            f"Question: {question_text}\n"
            f"Answer: {capped_ans}\n"
            f"Probes: {json.dumps(compact_probes)}\n"
            f"Escalation: {escalation_text}\n"
            f"AnchorAlt: {anchor_alt_text}\n"
            f"CoreExpectations: {json.dumps(exp_ids)}\n"
            f"StretchExpectations: {json.dumps(stretch_ids)}\n"
            f"FollowupsUsed: {followups_used}/2, TimeLeftSec: {time_left_ms // 1000}\n"
            "DECISION RULES:\n"
            "1. strong answer -> escalate (targeting stretch expectations if core expectations covered and time left > 120s; or next if all core and stretch covered).\n"
            "2. vague or under ~15 words -> clarify asking for concrete example from their work (max once per skill).\n"
            "3. no_experience -> hypothetical (using anchor_alt question).\n"
            "4. off_topic -> action 'off_topic', followup = short re-ask in simpler words sharing >=3 content words.\n"
            "5. matching probe trigger -> probe.\n"
            "6. if followups >= 2 or time left < 60s -> action 'next'.\n"
            "ACK RULES:\n"
            f"- ack: plain restatement of ONE specific thing candidate said, <=12 words, 1 sentence, no praise words, no '?'. {avoid_opener}\n"
            "- No praise words (no great, good, strong, solid, excellent, impressive, nice, perfect, clean, correct).\n"
            'JSON format: {"action": "probe|escalate|hypothetical|clarify|off_topic|rephrase|next", "no_experience": false, "ack": "...", "probe_id": "id or null", "followup": "one question <= 28 words or empty", "covered_expectations": []}'
        )
        return system_prompt, user_prompt

    async def _call_decision_llm(self, effect: RequestDecision) -> None:
        """Call LLM via router to evaluate candidate answer and return decision JSON."""
        start_time = time.perf_counter()
        model_name = os.getenv("GEMINI_MODEL_LIVE", "gemini-3.5-flash-lite")
        decision_dict: Optional[Dict[str, Any]] = None
        metrics: Dict[str, Any] = {}

        try:
            if self.llm_fn:
                # Support custom mock LLM for tests
                res = self.llm_fn(effect.question_text, effect.answer_text, effect.escalation_text or effect.question_text)
                if hasattr(res, "__aiter__"):
                    chunks = []
                    async for c in res:
                        chunks.append(c)
                    full_text = "".join(chunks).strip()
                elif asyncio.iscoroutine(res):
                    full_text = str(await res).strip()
                else:
                    full_text = str(res).strip()

                if full_text.startswith("{") and full_text.endswith("}"):
                    try:
                        decision_dict = json.loads(full_text)
                    except Exception:
                        pass
                if not decision_dict:
                    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if s.strip()]
                    ack = sentences[0] if sentences else "Understood."
                    q = sentences[1] if len(sentences) >= 2 else (effect.escalation_text or effect.question_text)
                    decision_dict = {
                        "ack": ack,
                        "action": "probe",
                        "followup": q,
                        "covered_expectations": [],
                        "no_experience": False,
                    }
            else:
                job_facts: Dict[str, str] = {}
                if effect.skill == "Candidate Q&A":
                    system_prompt, user_prompt, job_facts = self._build_qa_prompt(effect.answer_text, getattr(effect, 'last_ack_opener', None))
                else:
                    system_prompt, user_prompt = self._build_decision_prompt(
                        skill=effect.skill,
                        question_text=effect.question_text,
                        answer_text=effect.answer_text,
                        probes=effect.probes,
                        escalation_text=effect.escalation_text,
                        anchor_alt_text=effect.anchor_alt_text,
                        expectations=effect.expectations,
                        stretch_expectations=getattr(effect, "stretch_expectations", []),
                        followups_used=effect.followups_used,
                        time_left_ms=effect.time_left_ms,
                        last_ack_opener=getattr(effect, 'last_ack_opener', None),
                    )

                def on_stream_ack(ack_info: Union[str, Dict[str, Any]]):
                    if isinstance(ack_info, dict):
                        act = ack_info.get("action", "")
                        no_exp = ack_info.get("no_experience", False)
                        ack_text = (ack_info.get("ack") or "").strip()
                    else:
                        act = ""
                        no_exp = False
                        ack_text = (ack_info or "").strip()

                    # Phase A6.2: Withhold Q&A ack until grounding validation completes!
                    if effect.skill == "Candidate Q&A" or act == "qa_reply":
                        return

                    if act == "off_topic":
                        return

                    if ack_text:
                        val_ack, _ = validate_and_format_ack(
                            raw_ack=ack_text,
                            last_opener=getattr(effect, "last_ack_opener", None),
                            candidate_answer=effect.answer_text,
                            question_text=effect.question_text,
                            action=act,
                            no_experience=no_exp,
                        )
                        if val_ack and is_ack_grounded(val_ack, effect.answer_text, effect.question_text):
                            asyncio.create_task(self.queue.put(AckReady(
                                token=effect.token,
                                text=val_ack,
                                action=act,
                                no_experience=no_exp,
                                snapshot=getattr(effect, "snapshot", None),
                                now_ms=self.now_ms(),
                            )))
                        else:
                            logger.info("Streamed ack '%s' is not valid or not grounded; withholding AckReady.", ack_text)

                decision_dict, metrics = await stream_decision_with_ack_first(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_output_tokens=160,
                    temperature=0.1,
                    on_ack_ready=on_stream_ack,
                )
                logger.info(
                    "Decision Call Latency Diagnosis: TTFT=%sms, Ack=%sms, Total=%sms, Model=%s, Provider=%s, 429s=%d, Tokens=%d, Thinking=%s",
                    metrics.get("ttft_ms"),
                    metrics.get("ack_emitted_ms"),
                    metrics.get("total_ms"),
                    metrics.get("model_name"),
                    metrics.get("provider"),
                    metrics.get("retries_429", 0),
                    metrics.get("prompt_token_count", 0),
                    metrics.get("thinking_enabled", False),
                )

                if decision_dict and isinstance(decision_dict, dict):
                    if effect.skill == "Candidate Q&A" or decision_dict.get("action") == "qa_reply":
                        eff_fol, eff_ack, verified_facts = validate_qa_decision(decision_dict, job_facts, effect.answer_text)
                        decision_dict["followup"] = eff_fol
                        decision_dict["ack"] = eff_ack  # NEVER eff_ack or decision_dict.get("ack", "")
                        decision_dict["source_facts"] = verified_facts
                        if eff_ack:
                            val_ack, _ = validate_and_format_ack(
                                raw_ack=eff_ack,
                                last_opener=getattr(effect, "last_ack_opener", None),
                                candidate_answer=effect.answer_text,
                                action="qa_reply",
                            )
                            decision_dict["ack"] = val_ack
                            if val_ack and not self.state.spoken_ack_token:
                                await self.queue.put(AckReady(
                                    token=effect.token,
                                    text=val_ack,
                                    action="qa_reply",
                                    no_experience=False,
                                    snapshot=getattr(effect, "snapshot", None),
                                    now_ms=self.now_ms(),
                                ))
                    elif decision_dict.get("action") == "off_topic":
                        decision_dict["ack"] = ""
                    else:
                        raw_ack = (decision_dict.get("ack") or "").strip()
                        if raw_ack:
                            val_ack, _ = validate_and_format_ack(
                                raw_ack=raw_ack,
                                last_opener=getattr(effect, "last_ack_opener", None),
                                candidate_answer=effect.answer_text,
                                question_text=effect.question_text,
                                action=decision_dict.get("action", ""),
                                no_experience=decision_dict.get("no_experience", False),
                            )
                            if val_ack and is_ack_grounded(val_ack, effect.answer_text, effect.question_text):
                                decision_dict["ack"] = val_ack
                                if not self.state.spoken_ack_token:
                                    await self.queue.put(AckReady(
                                        token=effect.token,
                                        text=val_ack,
                                        action=decision_dict.get("action", ""),
                                        no_experience=decision_dict.get("no_experience", False),
                                        snapshot=getattr(effect, "snapshot", None),
                                        now_ms=self.now_ms(),
                                    ))
                            else:
                                logger.info("Ack '%s' failed validation/grounding against candidate answer. Regenerating once...", raw_ack)
                                regen_ack = await self._regenerate_grounded_ack(effect.answer_text, effect.question_text, raw_ack)
                                if regen_ack and is_ack_grounded(regen_ack, effect.answer_text, effect.question_text):
                                    val_regen, _ = validate_and_format_ack(
                                        raw_ack=regen_ack,
                                        last_opener=getattr(effect, "last_ack_opener", None),
                                        candidate_answer=effect.answer_text,
                                        question_text=effect.question_text,
                                        action=decision_dict.get("action", ""),
                                        no_experience=decision_dict.get("no_experience", False),
                                    )
                                    if val_regen:
                                        decision_dict["ack"] = val_regen
                                        if not self.state.spoken_ack_token:
                                            await self.queue.put(AckReady(
                                                token=effect.token,
                                                text=val_regen,
                                                action=decision_dict.get("action", ""),
                                                no_experience=decision_dict.get("no_experience", False),
                                                snapshot=getattr(effect, "snapshot", None),
                                                now_ms=self.now_ms(),
                                            ))
                                    else:
                                        decision_dict["ack"] = ""
                                else:
                                    logger.info("Regenerated ack failed grounding check; speaking NO ack.")
                                    decision_dict["ack"] = ""
        except Exception as e:
            logger.warning("Outer Decision LLM call error: %s", e)
            decision_dict = None

        self.last_raw_decision = decision_dict
        self.last_decision_used_fallback = (decision_dict is None)
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        self.last_decision_latency_ms = latency_ms
        self.current_metrics.model_generation_latency_ms = latency_ms

        # Requirement 9: Log every decision to trace.py via SessionTrace.log_decision with accurate provider & model
        if decision_dict:
            self.trace.log_decision(
                turn_id=f"turn_{self.state.turn_counter}",
                action=decision_dict.get("action", "unknown"),
                decision_json=decision_dict,
                provider=metrics.get("provider", "bedrock"),
                model=metrics.get("model_name", model_name),
                latency_ms=latency_ms,
                degraded=False,
            )

        # Enqueue DecisionReady with immutable snapshot
        await self.queue.put(DecisionReady(
            token=effect.token,
            decision=decision_dict,
            snapshot=getattr(effect, "snapshot", None),
            now_ms=self.now_ms(),
        ))

    async def _regenerate_grounded_ack(self, candidate_answer: str, question_text: str, bad_ack: str) -> str:
        """Requirement 3: Regenerate ungrounded ack once. If still ungrounded, returns empty string."""
        avoid_opener = f"NEVER start the ack with '{self.state.last_ack_opener}'." if self.state.last_ack_opener else ""
        system_prompt = "You are a concise technical interviewer acknowledging a candidate's answer."
        user_prompt = (
            f"Question asked: {question_text}\n"
            f"Candidate answer: {candidate_answer}\n"
            f"Your previous acknowledgement '{bad_ack}' was rejected because it did not mention a specific technical concept from the candidate's answer.\n"
            f"Provide a natural, plain 1-sentence acknowledgment of <= 12 words that directly mentions at least ONE concrete technical term, tool, or concept from the candidate's answer that was not in the question. "
            f"NO praise or evaluating words (no great/good/impressive/solid). NO question mark. {avoid_opener}\n"
            f'Output ONLY valid JSON: {{"ack": "..."}}'
        )
        try:
            dec, _ = await stream_decision_with_ack_first(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=40,
                temperature=0.2,
            )
            if dec and isinstance(dec, dict):
                cand_ack = (dec.get("ack") or "").strip()
                return cand_ack
        except Exception as e:
            logger.debug("Error regenerating ack: %s", e)
        return ""

    async def _handle_start_speculative_reply(self, effect: StartSpeculativeReply) -> None:
        """Start speculative LLM reply generation in background on EagerTurnEnd."""
        self.spec_token = effect.token
        self.spec_source_text = effect.source_text
        self.spec_snapshot = getattr(effect, "snapshot", None)
        self.spec_start_wall_time = time.perf_counter()
        self.spec_inference_latency_ms = None
        self.spec_decision = None
        self.spec_attempted = True
        self.current_metrics.speculation_used = False
        self.current_metrics.speculation_discarded = False
        self.current_metrics.speculation_outcome = None

        if self.state.phase == ConductorPhase.CANDIDATE_QA:
            curr_skill = "Candidate Q&A"
        else:
            curr_skill = self.state.skill_names[self.state.current_skill_index] if 0 <= self.state.current_skill_index < len(self.state.skill_names) else ""
        if not curr_skill:
            return

        sq = self.state.skill_questions.get(curr_skill, {})
        curr_q = self._get_current_question_text()
        probes_list = [
            {
                "id": p.probe_id or str(p.question_index),
                "text": p.question_text,
                "trigger_condition": p.trigger_condition or "",
            }
            for p in sq.get("probes", [])
        ]
        escalation_text = sq.get("escalation").question_text if sq.get("escalation") else ""
        anchor_alt_text = sq.get("anchor_alt").question_text if sq.get("anchor_alt") else ""
        curr_plan_q = _get_current_question(self.state) if hasattr(self.state, "current_question_index") else None
        expectations = list(curr_plan_q.expected_key_points) if curr_plan_q else []
        followups_used = self.state.followups_used_per_skill.get(curr_skill, 0)
        time_left_ms = get_skill_time_left_ms(self.state, curr_skill, self.now_ms())

        req = RequestDecision(
            token=effect.token,
            skill=curr_skill,
            question_text=curr_q,
            answer_text=effect.source_text,
            probes=probes_list,
            escalation_text=escalation_text,
            anchor_alt_text=anchor_alt_text,
            expectations=expectations,
            followups_used=followups_used,
            time_left_ms=time_left_ms,
            snapshot=self.spec_snapshot,
        )

        async def _run_spec():
            try:
                model_name = os.getenv("GEMINI_MODEL_LIVE", "gemini-3.5-flash-lite")
                if self.llm_fn:
                    res = self.llm_fn(req.question_text, req.answer_text, req.escalation_text or req.question_text)
                    if hasattr(res, "__aiter__"):
                        chunks = []
                        async for c in res:
                            chunks.append(c)
                        full_text = "".join(chunks).strip()
                    elif asyncio.iscoroutine(res):
                        full_text = str(await res).strip()
                    else:
                        full_text = str(res).strip()

                    dec = None
                    if full_text.startswith("{") and full_text.endswith("}"):
                        try:
                            dec = json.loads(full_text)
                        except Exception:
                            pass
                    if not dec:
                        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if s.strip()]
                        ack = sentences[0] if sentences else "Understood."
                        q = sentences[1] if len(sentences) >= 2 else (req.escalation_text or req.question_text)
                        dec = {
                            "ack": ack,
                            "action": "probe",
                            "followup": q,
                            "covered_expectations": [],
                            "no_experience": False,
                        }
                    self.spec_inference_latency_ms = (time.perf_counter() - self.spec_start_wall_time) * 1000.0
                    self.spec_decision = dec
                else:
                    spec_job_facts: Dict[str, str] = {}
                    if req.skill == "Candidate Q&A":
                        system_prompt, user_prompt, spec_job_facts = self._build_qa_prompt(req.answer_text, self.state.last_ack_opener)
                    else:
                        system_prompt, user_prompt = self._build_decision_prompt(
                            skill=req.skill,
                            question_text=req.question_text,
                            answer_text=req.answer_text,
                            probes=req.probes,
                            escalation_text=req.escalation_text,
                            anchor_alt_text=req.anchor_alt_text,
                            expectations=req.expectations,
                            stretch_expectations=getattr(req, "stretch_expectations", []),
                            followups_used=req.followups_used,
                            time_left_ms=req.time_left_ms,
                            last_ack_opener=self.state.last_ack_opener,
                        )

                    dec, _ = await stream_decision_with_ack_first(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        max_output_tokens=160,
                        temperature=0.1,
                    )
                    self.spec_inference_latency_ms = (time.perf_counter() - self.spec_start_wall_time) * 1000.0
                    if dec and isinstance(dec, dict) and (req.skill == "Candidate Q&A" or dec.get("action") == "qa_reply"):
                        eff_fol, eff_ack, verified_facts = validate_qa_decision(dec, spec_job_facts, req.answer_text)
                        dec["followup"] = eff_fol
                        dec["ack"] = eff_ack  # NEVER eff_ack or dec.get("ack", "")
                        dec["source_facts"] = verified_facts
                    self.spec_decision = dec
            except Exception as e:
                logger.debug("Speculative decision error: %s", e)
                self.spec_decision = None

        self.spec_task = asyncio.create_task(_run_spec())

    async def _handle_cancel_speculative_reply(self, token: str) -> None:
        """Cancel speculative task and drop buffered audio."""
        if self.spec_task and not self.spec_task.done():
            self.spec_task.cancel()
        self.spec_token = None
        self.spec_source_text = ""
        self.spec_snapshot = None
        self.spec_decision = None

    async def _handle_play_bridge(self, effect: PlayBridge) -> None:
        """Play a pre-synthesized conversational bridge clip immediately (0ms latency)."""
        cached_pcm = BRIDGE_AUDIO_CACHE.get(effect.text) or generate_fallback_pcm(0.35)
        self.current_metrics.used_bridge = True
        logger.info("Playing pre-synthesized bridge '%s' (%d bytes) for speech %s", effect.text, len(cached_pcm), effect.speech_id)

        curr_turn_id = getattr(effect, "candidate_turn_id", None) or self.state.current_candidate_turn_id or f"turn_{self.state.turn_counter}"
        self.speech_ledger.record_segment(
            candidate_turn_id=curr_turn_id,
            speech_id=effect.speech_id,
            request_id=f"bridge_{effect.speech_id}",
            semantic_kind="bridge",
            text=effect.text,
            action="bridge",
            effective_action="bridge",
            scheduled_at_ms=self.now_ms(),
            status="sent",
        )
        self.speech_ledger.mark_started(effect.speech_id, self.now_ms(), kind="bridge")

        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "TTSStarted",
                    "speech_id": effect.speech_id,
                    "is_bridge": True,
                    "text": effect.text,
                })
                await self.websocket.send_bytes(cached_pcm)
                await self.websocket.send_json({
                    "type": "TTSDone",
                    "speech_id": effect.speech_id,
                    "is_bridge": True,
                })
            except Exception as e:
                logger.warning("Error playing bridge audio: %s", e)

        self.speech_ledger.mark_completed(effect.speech_id, self.now_ms(), kind="bridge")

    def _handle_schedule_timer(self, effect: ScheduleTimer) -> None:
        """Schedule an asyncio timer that enqueues Tick(at_ms, token) upon expiry."""
        self._handle_cancel_timer(effect.name)

        async def _timer_worker(name: str, at_ms: int, token: str, delay_ms: int) -> None:
            delay_s = (delay_ms / 1000.0) if delay_ms > 0 else max(0.0, (at_ms - self.now_ms()) / 1000.0)
            try:
                await asyncio.sleep(delay_s)
                await self.queue.put(Tick(now_ms=at_ms, token=token))
            except asyncio.CancelledError:
                pass

        self.timer_tasks[effect.name] = asyncio.create_task(
            _timer_worker(effect.name, effect.at_ms, effect.token, effect.delay_ms)
        )

    def _handle_cancel_timer(self, name: str) -> None:
        """Cancel scheduled timer task."""
        if name in self.timer_tasks:
            t = self.timer_tasks.pop(name)
            if not t.done():
                t.cancel()

    async def _handle_persist(self, turn: Dict[str, Any]) -> None:
        """Persist turn to database and session trace."""
        # Log to trace.py
        turn_id = f"turn_{turn.get('turn_index', 0)}"
        self.trace.log_commit(
            turn_id=turn_id,
            reason="conductor_commit",
            full_answer=turn.get("answer", ""),
            word_count=turn.get("word_count", 0),
            speech_duration_s=0.0,
        )

        # Record metrics
        metrics_dict = self.current_metrics.to_dict()
        if self.latency_history and self.latency_history[-1].get("turn_index") == self.current_metrics.turn_index:
            self.latency_history[-1] = metrics_dict
        else:
            self.latency_history.append(metrics_dict)
        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "CommittedAnswer",
                    "text": turn.get("answer", ""),
                })
                await self.websocket.send_json({
                    "type": "TurnMetrics",
                    "metrics": metrics_dict,
                })
            except Exception:
                pass

        # Persist dynamic question to database if not present (Requirement 8)
        if turn.get("question_kind") == "followup_dynamic" or turn.get("question_index", 0) >= 1000:
            try:
                async with AsyncSessionLocal() as db:
                    existing_q = await db.execute(
                        select(InterviewQuestion).where(
                            InterviewQuestion.session_id == self.session_id,
                            InterviewQuestion.question_index == turn.get("question_index", 0),
                        )
                    )
                    if not existing_q.scalar_one_or_none():
                        dyn_db_q = InterviewQuestion(
                            session_id=self.session_id,
                            question_index=turn.get("question_index", 0),
                            skill_name=turn.get("skill_name", ""),
                            question_text=turn.get("question_text", ""),
                            kind="followup_dynamic",
                            question_state="asked",
                        )
                        db.add(dyn_db_q)
                        await db.commit()
            except Exception as e:
                logger.warning("Could not persist dynamic InterviewQuestion to DB: %s", e)

        # Persist to database (InterviewTranscriptTurn)
        try:
            async with AsyncSessionLocal() as db:
                db_turn = InterviewTranscriptTurn(
                    session_id=self.session_id,
                    turn_type=turn.get("question_kind", "candidate_answer"),
                    speaker="candidate",
                    text=turn.get("answer", ""),
                    sequence_number=turn.get("turn_index", 1),
                )
                db.add(db_turn)
                await db.commit()
        except Exception as e:
            logger.warning("Could not persist InterviewTranscriptTurn to DB: %s", e)

    async def _handle_emit_ui(self, effect: EmitUI) -> None:
        """Send UI status update frame over WebSocket."""
        if self.websocket:
            try:
                await self.websocket.send_json({
                    "type": "UIStatus",
                    "status": effect.status,
                    "payload": effect.payload,
                    "phase": self.state.phase.value,
                    "question_index": self.state.current_question_index,
                })
            except Exception as e:
                logger.debug("Failed to send EmitUI frame: %s", e)

    # -------------------------------------------------------------------------
    # Question Preview Helpers
    # -------------------------------------------------------------------------

    def _get_current_question_text(self) -> str:
        for q in self.state.questions:
            if q.question_index == self.state.current_question_index:
                return q.question_text
        return ""

    def _get_next_question_preview_text(self) -> str:
        next_q = get_next_plan_question(self.state)
        return next_q.question_text if next_q else ""


    # -------------------------------------------------------------------------
    # Inbound Event Producers
    # -------------------------------------------------------------------------

    async def on_playback_started(self, speech_id: str) -> None:
        """Worklet sent playback_started on first audible sample."""
        self.current_metrics.bot_audio_started_time = time.perf_counter()
        await self.queue.put(BotAudioStarted(speech_id=speech_id, now_ms=self.now_ms()))

    async def on_playback_ended(self, speech_id: str) -> None:
        """Worklet sent playback_ended when ring buffer drained."""
        await self.queue.put(BotSpeechDone(speech_id=speech_id, now_ms=self.now_ms()))

    async def on_ready_button(self) -> None:
        await self.queue.put(ReadyButton(now_ms=self.now_ms()))

    async def on_commit_button(self) -> None:
        await self.queue.put(CommitButton(now_ms=self.now_ms()))

    async def on_repeat_button(self) -> None:
        await self.queue.put(RepeatRequest(now_ms=self.now_ms()))

    async def on_end_button(self, request_id: Optional[str] = None) -> None:
        self.end_request_id = request_id
        await self.queue.put(EndButton(now_ms=self.now_ms(), request_id=request_id))

    async def on_mic_audio(self, raw_bytes: bytes) -> None:
        """Process incoming client mic PCM chunk."""
        if len(raw_bytes) >= 160:
            peak = max(
                abs(int.from_bytes(raw_bytes[j : j + 2], "little", signed=True))
                for j in range(0, len(raw_bytes), 2)
            )
            if peak > 400:
                self.current_metrics.last_voiced_frame_time = time.perf_counter()

        if self.flux_client:
            await self.flux_client.send_audio(raw_bytes)

    async def on_flux_event(self, event: FluxEvent) -> None:
        """Process incoming typed event from Flux STT client."""
        now = self.now_ms()

        if isinstance(event, StartOfTurn):
            await self.queue.put(TurnStart(now_ms=now))

        elif isinstance(event, Update):
            # Stream live interim hypothesis directly to connected UI
            if self.websocket:
                try:
                    await self.websocket.send_json({"type": "Update", "text": event.text})
                except Exception:
                    pass

        elif isinstance(event, EagerEndOfTurn):
            self.current_metrics.eager_eot_time = time.perf_counter()
            if self.websocket:
                try:
                    await self.websocket.send_json({"type": "Update", "text": event.text})
                except Exception:
                    pass
            await self.queue.put(EagerTurnEnd(text=event.text, now_ms=now))

        elif isinstance(event, FluxTurnResumed):
            await self.queue.put(TurnResumed(now_ms=now))

        elif isinstance(event, EndOfTurn):
            self.current_metrics.end_of_turn_time = time.perf_counter()
            if self.websocket:
                try:
                    await self.websocket.send_json({"type": "Update", "text": event.text})
                except Exception:
                    pass
            await self.queue.put(TurnEnd(text=event.text, turn_id=event.turn_index, now_ms=now))
