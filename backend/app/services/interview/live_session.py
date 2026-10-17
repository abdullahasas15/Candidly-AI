"""Live real-time interview orchestrator and state machine processor for Candidly AI.

Integrates Pipecat, SmallWebRTCTransport, Silero VAD, Smart Turn v3, Parakeet STT,
Kokoro TTS, Gemini Live streaming, PacingController, silence handling, pause/resume
resilience, latency instrumentation, and post-interview Judge triggering.
"""

import asyncio
from datetime import datetime, timezone
import os
import re
import time
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    InterviewIntegrityEvent,
    InterviewQuestion,
    InterviewSession,
    InterviewTranscriptTurn,
    JobPosting,
)
from backend.app.services.interview.followup_policy import (
    answer_candidate_closing_question,
    detect_fast_intent,
    pick_varied_ack,
    stream_turn_decision,
    stream_section_turn_decision,
    update_coverage_status,
    update_section_expectation_coverage_async,
    validate_coverage_quotes_verbatim,
)
from backend.app.services.interview.trace import SessionTrace
from backend.app.services.interview.state_machine import (
    InterviewPhase,
    PacingController,
    QuestionState,
    TurnType,
)
from backend.app.services.interview.turn_evaluator import evaluate_interview_session
from backend.app.services.interview.voice_pipeline import (
    build_voice_pipeline_components,
    pre_synthesize_phrase,
)

MAX_PAUSE_WINDOW_SECONDS = 15 * 60  # 15 minutes max pause window for reconnect
MIN_INTERRUPTION_SPEECH_DURATION_SECS = 0.35  # 350ms minimum sustained speech before barge-in triggers

_BACKCHANNEL_PHRASES = {
    "yeah", "yes", "yep", "uh-huh", "uh huh", "mhm", "mm-hmm", "mm hmm",
    "ok", "okay", "right", "got it", "i see", "sure", "cool", "ah", "yup",
}


def _is_backchannel(text: str) -> bool:
    import re
    cleaned = re.sub(r"[^\w\s]", "", (text or "").lower()).strip()
    return cleaned in _BACKCHANNEL_PHRASES


class InterviewerBusyError(RuntimeError):
    """Raised when another live voice interview is already active on this local MLX worker."""


class InterviewCoordinatorProcessor(FrameProcessor):
    """Orchestrates interview phases, streaming turn decisions, pacing, silence nudges, barge-in, and DB persistence."""

    def __init__(
        self,
        session_id: str,
        candidate_name: str,
        role_title: str,
        questions: List[Dict[str, Any]],
        candidate_local_hour: Optional[int] = None,
        max_followup_depth: int = 1,
        duration_planned_mins: float = 20.0,
        allow_grace_extension: bool = True,
        pacing_strictness: str = "Balanced",
        skill_time_allocations_mins: Optional[Dict[str, float]] = None,
        interviewer_brief: str = "",
        job_public_fields: Optional[Dict[str, Any]] = None,
        application_id: Optional[str] = None,
        integrity_policy_tier: str = "Moderate",
        speech_speed: float = 1.0,
        captions_enabled: bool = True,
        enable_silence_monitor: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.session_id = session_id
        self.application_id = application_id
        self.candidate_name = candidate_name or "Candidate"
        self.role_title = role_title or "Software Engineer"
        self.questions = questions or []
        self.candidate_local_hour = candidate_local_hour
        self.max_followup_depth = max_followup_depth
        self.interviewer_brief = interviewer_brief or ""
        self.job_public_fields = job_public_fields or {"job_title": self.role_title}
        self.integrity_policy_tier = integrity_policy_tier or "Moderate"
        self.speech_speed = speech_speed
        self.captions_enabled = captions_enabled
        self.enable_silence_monitor = enable_silence_monitor

        self.pacing = PacingController(
            duration_planned_mins=duration_planned_mins,
            allow_grace_extension=allow_grace_extension,
            pacing_strictness=pacing_strictness,
            skill_time_allocations_mins=skill_time_allocations_mins or {},
        )

        self.current_phase = InterviewPhase.GREETING
        self.current_question_index = 0
        self.in_followup = False
        self.is_speaking = False
        self.is_thinking = False
        self.has_begun = False
        self.is_completed = False
        self.current_turn_sequence = 0
        self.last_ai_speech = ""
        self.last_candidate_speech = ""
        self.running_summary = ""
        self.recent_turns: List[Dict[str, str]] = []
        self.lock = asyncio.Lock()

        # Blueprint section controller state (Checkpoint R3.4)
        self.is_blueprint_session: bool = False
        self.blueprint_id: Optional[str] = None
        self.welcome_question: Optional[Dict[str, Any]] = None
        self.intro_question: Optional[Dict[str, Any]] = None
        self.skill_sections: List[Dict[str, Any]] = []
        self.candidate_qa_question: Optional[Dict[str, Any]] = None
        self.closing_question: Optional[Dict[str, Any]] = None
        self.current_skill_section_index: int = 0
        self.section_state: Dict[str, Any] = {
            "current_section_phase": "not_started",
            "used_anchor_alt": False,
            "asked_probe_ids": set(),
            "asked_escalation": False,
            "section_started_monotonic": time.monotonic(),
        }
        self.intro_followup_count: int = 0
        self.candidate_qa_count: int = 0

        # Latency & interruption tracking state
        self._last_stt_final_ms: Optional[float] = None
        self._last_stt_confidence: Optional[float] = None
        self._candidate_speech_started_monotonic: Optional[float] = None
        self._candidate_speech_duration: float = 0.0
        self._active_candidate_turn_id: Optional[str] = None
        self._turn_confirmed_monotonic: Optional[float] = None
        self._pending_llm_ttft_ms: Optional[float] = None
        self._awaiting_first_bot_audio: bool = False
        self._active_ai_turn_id: Optional[str] = None
        self._active_ai_full_text: str = ""
        self._active_ai_started_monotonic: Optional[float] = None

        # Trace logger
        self.session_trace = SessionTrace(self.session_id)

        # Turn merge, accumulation & silence timer state
        self._merge_buffer: str = ""
        self._accumulated_speech_segments: List[str] = []
        self._accumulated_full_text: str = ""
        self._active_turn_id: int = 0
        self._commit_timer_task: Optional[asyncio.Task] = None
        self._active_turn_task: Optional[asyncio.Task] = None
        self._silence_task: Optional[asyncio.Task] = None
        self._last_activity_monotonic: float = time.monotonic()
        self._silence_nudge_count: int = 0
        self._consecutive_fragment_count: int = 0
        self._hold_extension_secs: float = 0.0
        self._audio_segments_received_fn = lambda: 1
        self._stt_service: Optional[Any] = None

    def record_stt_interim(self, interim_text: str) -> None:
        """Lane 1 interim caption: update UI live as words are spoken."""
        clean = (interim_text or "").strip()
        if not clean:
            return
        self._last_activity_monotonic = time.monotonic()
        live_text = f"{self._accumulated_full_text} {clean}".strip() if self._accumulated_full_text else clean
        asyncio.create_task(
            self.emit_ui_state("candidate-speech-transcript", {"text": live_text, "is_interim": True})
        )

    def record_stt_metrics(self, text: str, stt_ms: float, confidence: Optional[float] = None, seq: int = 0) -> None:
        """Lane 2 accuracy segment: append to accumulated speech and update UI."""
        clean = (text or "").strip()
        if not clean:
            return
        self._last_stt_final_ms = stt_ms
        self._last_stt_confidence = confidence
        self._last_activity_monotonic = time.monotonic()
        self._accumulated_speech_segments.append(clean)
        self._accumulated_full_text = " ".join(self._accumulated_speech_segments).strip()
        asyncio.create_task(
            self.emit_ui_state(
                "candidate-speech-transcript",
                {"text": self._accumulated_full_text, "is_interim": False, "seq": seq},
            )
        )
        # Schedule turn commit
        self._schedule_turn_commit()

    def _schedule_turn_commit(self) -> None:
        """Schedule turn commit with merge window (1.5s) and trailing-thought detection (up to 2.5s)."""
        if self._commit_timer_task and not self._commit_timer_task.done():
            self._commit_timer_task.cancel()

        text = self._accumulated_full_text.strip()
        if not text:
            return

        trailing_thought = bool(
            re.search(r"(?i)\b(because|and|or|so|like|which|but|if|when|also)\s*$", text)
            or text.endswith(",")
        )
        # Wait up to 2.5s if trailing thought, else 1.2s silence
        timeout = 2.5 if trailing_thought else 1.2
        self._commit_timer_task = asyncio.create_task(self._commit_turn_after_delay(timeout))

    async def _commit_turn_after_delay(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._commit_full_turn()
        except asyncio.CancelledError:
            pass

    async def _commit_full_turn(self) -> None:
        """Commits accumulated speech segments into a single full candidate turn."""
        candidate_text = self._accumulated_full_text.strip()
        self._accumulated_speech_segments = []
        self._accumulated_full_text = ""
        if not candidate_text:
            return

        self._active_turn_id += 1
        curr_turn_id = self._active_turn_id
        words = candidate_text.split()

        # Fragment Guard: answers < 6 words and not affirmative
        is_affirmative = bool(
            re.match(r"^(yes|yep|yeah|sure|ready|sounds good|i am|ok|okay|let's go|let's do it)[.!]?$", candidate_text.lower().strip())
        ) or (self.current_phase in (InterviewPhase.GREETING, InterviewPhase.READY_CHECK))

        # R3.4b: Fast intents ("I don't know", "no", "not sure", "pass", "haven't done that", hold, clarify, repeat)
        # are conversational intents, NOT fragments!
        fast_intent = detect_fast_intent(
            candidate_text,
            follow_up_count=len(self.section_state.get("asked_probe_ids", set())) if isinstance(self.section_state, dict) else 0,
            question_text=getattr(self, "current_question_text", ""),
        )

        if fast_intent is not None:
            self._consecutive_fragment_count = 0
        elif len(words) < 6 and not is_affirmative and self.current_phase == InterviewPhase.DEEP_DIVE:
            self._consecutive_fragment_count += 1
            if self._consecutive_fragment_count >= 2:
                logger.info(
                    f"Fragment Guard: 2 consecutive 'please go on' triggers reached for '{candidate_text}'. Treating as DONT_KNOW and moving on."
                )
                self._consecutive_fragment_count = 0
                candidate_text = "I don't know, let's move on."
                words = candidate_text.split()
            else:
                logger.info(f"Fragment Guard triggered on short answer ({len(words)} words): '{candidate_text}' (consecutive={self._consecutive_fragment_count})")
                hold_reply = "Please go on, I'm listening."
                self.last_ai_speech = hold_reply
                self.session_trace.log_commit(
                    turn_id=str(curr_turn_id),
                    reason="fragment_guard_hold",
                    full_answer=candidate_text,
                    word_count=len(words),
                    speech_duration_s=self._candidate_speech_duration,
                )
                await self.persist_turn(
                    turn_type=TurnType.CLARIFICATION.value,
                    speaker="ai",
                    text=hold_reply,
                )
                await self.emit_ui_state("ai-speech-transcript", {"text": hold_reply, "phase": self.current_phase.value})
                await self.emit_ui_state("interview-bot-state", {"state": "listening"})
                await self.push_frame(TTSSpeakFrame(hold_reply))
                return
        else:
            self._consecutive_fragment_count = 0

        self.session_trace.log_commit(
            turn_id=str(curr_turn_id),
            reason="silence_timeout",
            full_answer=candidate_text,
            word_count=len(words),
            speech_duration_s=self._candidate_speech_duration,
        )

        if self._active_turn_task and not self._active_turn_task.done():
            self._active_turn_task.cancel()
        self._active_turn_task = asyncio.create_task(self.handle_candidate_answer(candidate_text, curr_turn_id))

    def record_tts_first_audio(self, tts_ms: float) -> None:
        if not self._awaiting_first_bot_audio or not self._active_candidate_turn_id:
            return
        self._awaiting_first_bot_audio = False
        total_ms = (
            round((time.perf_counter() - self._turn_confirmed_monotonic) * 1000.0, 2)
            if self._turn_confirmed_monotonic is not None
            else tts_ms
        )
        turn_id = self._active_candidate_turn_id
        llm_ms = self._pending_llm_ttft_ms
        stt_ms = self._last_stt_final_ms
        asyncio.create_task(
            self._update_turn_latency(
                turn_id=turn_id,
                stt_final_ms=stt_ms,
                llm_ttft_ms=llm_ms,
                tts_first_audio_ms=tts_ms,
                total_response_ms=total_ms,
            )
        )

    async def _update_turn_latency(
        self,
        *,
        turn_id: str,
        stt_final_ms: Optional[float],
        llm_ttft_ms: Optional[float],
        tts_first_audio_ms: Optional[float],
        total_response_ms: Optional[float],
    ) -> None:
        try:
            async with AsyncSessionLocal() as db:
                turn = (
                    await db.execute(
                        select(InterviewTranscriptTurn).where(InterviewTranscriptTurn.id == turn_id)
                    )
                ).scalars().first()
                if turn:
                    if stt_final_ms is not None:
                        turn.stt_final_ms = stt_final_ms
                    if llm_ttft_ms is not None:
                        turn.llm_ttft_ms = llm_ttft_ms
                    if tts_first_audio_ms is not None:
                        turn.tts_first_audio_ms = tts_first_audio_ms
                    if total_response_ms is not None:
                        turn.total_response_ms = total_response_ms
                    await db.commit()
        except Exception as exc:
            logger.debug(f"Latency update notice for turn {turn_id}: {exc}")

    async def init_sequence_from_db(self) -> Optional[InterviewSession]:
        """Query DB to resume sequence_number and session state safely (supports pause/reconnect)."""
        try:
            async with AsyncSessionLocal() as db:
                stmt = (
                    select(InterviewTranscriptTurn.sequence_number)
                    .where(InterviewTranscriptTurn.session_id == self.session_id)
                    .order_by(InterviewTranscriptTurn.sequence_number.desc())
                )
                res = await db.execute(stmt)
                last = res.scalars().first()
                self.current_turn_sequence = (last + 1) if last is not None else 0

                sess_stmt = (
                    select(InterviewSession)
                    .where(InterviewSession.id == self.session_id)
                    .options(selectinload(InterviewSession.job))
                )
                session = (await db.execute(sess_stmt)).scalars().first()
                if session and session.job:
                    job = session.job
                    self.job_public_fields = {
                        "job_title": getattr(job, "job_title", self.role_title) or self.role_title,
                        "department": getattr(job, "department", "Engineering"),
                        "seniority_level": getattr(job, "seniority_level", "Mid-Level"),
                        "job_description": getattr(job, "job_description", ""),
                        "requirements": getattr(job, "requirements", ""),
                        "responsibilities": getattr(job, "responsibilities", ""),
                        "workplace_model": getattr(job, "workplace_model", "flexible"),
                    }
                if session and session.blueprint_id:
                    self.is_blueprint_session = True
                    self.blueprint_id = session.blueprint_id
                    await self._load_blueprint_structure(session, db)
                return session
        except Exception as e:
            logger.error(f"Error initializing turn sequence: {e}")
            self.current_turn_sequence = 0
            return None

    async def _load_blueprint_structure(self, session: InterviewSession, db: AsyncSession):
        """Organize materialized interview questions into structured sections (R3.3/R3.4)."""
        from backend.app.models import BlueprintSection, SessionExpectationCoverage
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        # 1. Fetch blueprint sections
        sec_stmt = (
            select(BlueprintSection)
            .where(BlueprintSection.blueprint_id == session.blueprint_id)
            .order_by(BlueprintSection.order_index)
            .options(selectinload(BlueprintSection.expectations))
        )
        bp_sections = (await db.execute(sec_stmt)).scalars().all()

        # 2. Fetch all materialized questions for this session
        q_stmt = (
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == self.session_id)
            .order_by(InterviewQuestion.question_index)
        )
        all_qs = (await db.execute(q_stmt)).scalars().all()

        # 3. Fetch expectation coverages
        cov_stmt = (
            select(SessionExpectationCoverage)
            .where(SessionExpectationCoverage.session_id == self.session_id)
            .options(selectinload(SessionExpectationCoverage.expectation))
        )
        all_covs = (await db.execute(cov_stmt)).scalars().all()
        cov_by_exp_id = {c.expectation_id: c for c in all_covs}

        # 4. Map questions by kind and by section_id
        qs_by_kind = {}
        qs_by_sec_id = {}
        for q in all_qs:
            q_dict = {
                "id": q.id,
                "question_index": q.question_index,
                "skill_name": q.skill_name,
                "priority_tier": q.priority_tier,
                "question_text": q.question_text,
                "kind": q.kind,
                "section_id": q.section_id,
                "trigger_condition": (q.personalization_context or {}).get("trigger_condition") if isinstance(q.personalization_context, dict) else None,
                "target_expectation_ids": q.target_expectation_ids or [],
            }
            if q.kind:
                qs_by_kind.setdefault(q.kind, []).append(q_dict)
            if q.section_id:
                qs_by_sec_id.setdefault(q.section_id, []).append(q_dict)

        self.welcome_question = (qs_by_kind.get("welcome") or [None])[0]
        self.intro_question = (qs_by_kind.get("intro_hook") or [None])[0]
        self.candidate_qa_question = (qs_by_kind.get("candidate_qa") or [None])[0]
        self.closing_question = (qs_by_kind.get("closing") or [None])[0]

        # 5. Build structured skill sections
        self.skill_sections = []
        for s in bp_sections:
            if s.section_type != "skill":
                continue
            sec_qs = qs_by_sec_id.get(s.id, [])
            anchor_q = next((q for q in sec_qs if q["kind"] == "anchor"), None)
            anchor_alt_q = next((q for q in sec_qs if q["kind"] == "anchor_alt"), None)
            escalation_q = next((q for q in sec_qs if q["kind"] == "escalation"), None)
            probes = [q for q in sec_qs if q["kind"] == "probe"]
            resume_probe = next((q for q in sec_qs if q["kind"] == "resume_probe"), None)

            exps = [
                {
                    "id": e.id,
                    "expectation_text": e.expectation_text,
                    "importance": getattr(e, "importance", "core"),
                    "status": cov_by_exp_id[e.id].status if e.id in cov_by_exp_id else "not_probed",
                }
                for e in (s.expectations or [])
            ]

            self.skill_sections.append({
                "section_id": s.id,
                "skill_name": s.skill_name or s.title,
                "priority_tier": s.priority_tier or "P0",
                "allocated_minutes": float(s.allocated_minutes or 4.0),
                "transition_script": getattr(s, "transition_script", None),
                "spoken_topic_label": getattr(s, "spoken_topic_label", None) or s.skill_name or s.title,
                "anchor_q": anchor_q,
                "anchor_alt_q": anchor_alt_q,
                "escalation_q": escalation_q,
                "probes": probes,
                "resume_probe": resume_probe,
                "expectations": exps,
            })

        logger.info(
            "Loaded blueprint structure for session %s: %d skill sections",
            self.session_id, len(self.skill_sections),
        )

    def _next_sequence(self) -> int:
        seq = self.current_turn_sequence
        self.current_turn_sequence += 1
        return seq

    async def persist_turn(
        self,
        turn_type: str,
        speaker: str,
        text: str,
        question_id: Optional[str] = None,
        confidence: Optional[float] = None,
        stt_final_ms: Optional[float] = None,
        llm_ttft_ms: Optional[float] = None,
        tts_first_audio_ms: Optional[float] = None,
        total_response_ms: Optional[float] = None,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> InterviewTranscriptTurn:
        """Durable persistence to interview_transcript_turns."""
        seq = self._next_sequence()
        clean_text = text.strip()
        turn = InterviewTranscriptTurn(
            session_id=self.session_id,
            question_id=question_id,
            turn_type=turn_type,
            speaker=speaker,
            text=clean_text,
            spoken_text=clean_text if speaker == "ai" else None,
            was_interrupted=False,
            audio_ref=None,
            stt_confidence=confidence,
            stt_final_ms=stt_final_ms,
            llm_ttft_ms=llm_ttft_ms,
            tts_first_audio_ms=tts_first_audio_ms,
            total_response_ms=total_response_ms,
            provider=provider,
            model_name=model_name,
            sequence_number=seq,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        async with AsyncSessionLocal() as db:
            db.add(turn)
            await db.commit()
            await db.refresh(turn)

        self.recent_turns.append({"speaker": speaker, "text": clean_text, "turn_id": turn.id})
        if len(self.recent_turns) > 8:
            self.recent_turns = self.recent_turns[-8:]

        if speaker == "ai":
            if "?" in clean_text:
                if getattr(self, "_last_turn_was_ai_question", False):
                    logger.warning(
                        "ASSERTION WARNING: Consecutive AI question sequence detected without candidate response! "
                        "Last turn ID: %s | New AI question: %s",
                        self._active_ai_turn_id, clean_text
                    )
                self._last_turn_was_ai_question = True
            self._active_ai_turn_id = turn.id
            self._active_ai_full_text = clean_text
            self._active_ai_started_monotonic = time.monotonic()
        elif speaker == "candidate":
            self._last_turn_was_ai_question = False

        logger.info(f"Persisted turn [{seq}] ({turn_type}) {speaker}: {clean_text[:60]}...")
        return turn

    async def log_integrity_event(
        self,
        event_type: str,
        details_json: Dict[str, Any],
        turn_id: Optional[str] = None,
    ) -> None:
        """Persist an integrity event scaled by the job's integrity_policy_tier."""
        tier = (self.integrity_policy_tier or "Moderate").lower()
        base_high = {"prompt_injection", "multiple_faces", "paste"}
        if event_type in base_high:
            severity = "high" if tier != "relaxed" else "medium"
        else:
            severity = "medium" if tier == "strict" else "low"

        try:
            async with AsyncSessionLocal() as db:
                ev = InterviewIntegrityEvent(
                    session_id=self.session_id,
                    application_id=self.application_id,
                    event_type=event_type,
                    severity=severity,
                    policy_tier=self.integrity_policy_tier,
                    details_json=details_json,
                    turn_id=turn_id,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.add(ev)
                await db.commit()
        except Exception as exc:
            logger.debug(f"Integrity event log notice: {exc}")

    async def emit_ui_state(self, message_type: str, payload: Dict[str, Any]):
        """Emit client-safe status frame over WebRTC data channel via RTVI (redacted of rubrics/scores)."""
        clean_payload = {
            "type": message_type,
            "session_id": self.session_id,
            "phase": self.current_phase.value,
            "remaining_seconds": round(self.pacing.remaining_seconds(), 1),
            "grace_extended": self.pacing.grace_extended,
            "captions_enabled": self.captions_enabled,
            "speech_speed": self.speech_speed,
            "timestamp": time.time(),
            **payload,
        }
        await self.push_frame(
            RTVIServerMessageFrame(data=clean_payload),
            FrameDirection.DOWNSTREAM,
        )

    def _build_greeting_and_ready_check(self) -> tuple[str, str]:
        if self.is_blueprint_session:
            first_name = self.candidate_name.split()[0] if self.candidate_name else "Candidate"
            spoken_topics = [
                s.get("spoken_topic_label") or s.get("skill_name")
                for s in self.skill_sections
                if s.get("skill_name")
            ]
            agenda_str = ", ".join(spoken_topics[:-1]) + f", and {spoken_topics[-1]}" if len(spoken_topics) > 1 else (spoken_topics[0] if spoken_topics else "technical topics")
            duration_mins = int(self.pacing.duration_planned_mins)
            greeting_text = (
                f"Hi {first_name}, I'm your AI interviewer for the {self.role_title} role. "
                f"Our interview today is scheduled for {duration_mins} minutes. "
                f"This session is monitored per our integrity policy and audio is transcribed in real time without audio recording stored. "
                f"Today we will cover {agenda_str}, followed by time for any questions you have for us. "
                f"Feel free to ask me to repeat any question or take a moment if you need one."
            )
            ready_text = "Ready to begin?"
            return greeting_text, ready_text

        hour = self.candidate_local_hour if self.candidate_local_hour is not None else datetime.now().hour
        if hour < 12:
            tod = "Good morning"
        elif hour < 17:
            tod = "Good afternoon"
        else:
            tod = "Good evening"

        greeting_text = (
            f"{tod}, {self.candidate_name}. Welcome to your interview for the "
            f"{self.role_title} role."
        )
        ready_text = "Before we dive in, can you hear me clearly and are you ready to begin?"
        return greeting_text, ready_text

    async def begin_interview(self):
        """Triggered by candidate click on 'Begin'. Supports fresh start and paused session resume."""
        async with self.lock:
            if self.has_begun:
                return
            self.has_begun = True
            db_session = await self.init_sequence_from_db()
            self.pacing.started_monotonic = time.monotonic()
            self.pacing.mark_question_started()

            # Check if reconnecting to a paused session within the pause window (Part C1)
            is_resuming = False
            if db_session and db_session.status == "paused" and db_session.paused_at:
                pause_age = (datetime.now(timezone.utc).replace(tzinfo=None) - db_session.paused_at).total_seconds()
                if pause_age <= MAX_PAUSE_WINDOW_SECONDS and self.current_turn_sequence > 0:
                    is_resuming = True
                    self.current_question_index = min(
                        db_session.current_question_index or 0,
                        max(0, len(self.questions) - 1),
                    )
                    self.running_summary = db_session.running_summary or ""
                    try:
                        self.current_phase = InterviewPhase(db_session.current_phase or "deep_dive")
                    except ValueError:
                        self.current_phase = InterviewPhase.DEEP_DIVE

            async with AsyncSessionLocal() as db:
                s_row = (
                    await db.execute(select(InterviewSession).where(InterviewSession.id == self.session_id))
                ).scalars().first()
                if s_row:
                    s_row.status = "in_progress"
                    s_row.paused_at = None
                    if not s_row.started_at:
                        s_row.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await db.commit()

            if is_resuming and self.questions and self.current_phase == InterviewPhase.DEEP_DIVE:
                q = self.questions[self.current_question_index]
                welcome_back = f"Welcome back, {self.candidate_name}! Let's pick up right where we left off. {q['question_text']}"
                self.last_ai_speech = welcome_back
                await self.persist_turn(
                    turn_type=TurnType.MAIN_QUESTION.value,
                    speaker="ai",
                    text=welcome_back,
                    question_id=q.get("id"),
                )
                await self.emit_ui_state(
                    "interview-progress",
                    {
                        "question_index": self.current_question_index,
                        "total_questions": len(self.questions),
                        "question_text": q["question_text"],
                        "skill_name": q.get("skill_name"),
                        "resumed": True,
                    },
                )
                await self.emit_ui_state(
                    "ai-speech-transcript",
                    {"text": welcome_back, "question_text": q["question_text"], "phase": self.current_phase.value},
                )
                await self.push_frame(TTSSpeakFrame(welcome_back))
                self._start_silence_monitor()
                return

            # Fresh interview opening (Part B5): Greeting + Ready check
            greeting_text, ready_text = self._build_greeting_and_ready_check()
            await self.persist_turn(
                turn_type=TurnType.GREETING.value,
                speaker="ai",
                text=greeting_text,
            )
            await self.persist_turn(
                turn_type=TurnType.READY_CHECK.value,
                speaker="ai",
                text=ready_text,
            )

            self.current_phase = InterviewPhase.READY_CHECK
            combined_welcome = f"{greeting_text} {ready_text}"
            self.last_ai_speech = combined_welcome

            await self._persist_session_progress()
            await self.emit_ui_state(
                "interview-phase-change",
                {"phase": InterviewPhase.READY_CHECK.value, "text": combined_welcome},
            )
            await self.emit_ui_state(
                "ai-speech-transcript",
                {"text": combined_welcome, "phase": InterviewPhase.READY_CHECK.value},
            )

            logger.info(f"=== [AI Interviewer Voice] Speaking opening ready-check: '{combined_welcome}' ===")
            await self.push_frame(TTSSpeakFrame(combined_welcome))
            self._start_silence_monitor()

    async def repeat_current_question(self) -> str:
        """Triggered by candidate voice 'repeat that' or UI 'Repeat question' button (does not consume follow-up)."""
        async with self.lock:
            self._reset_silence_timer()
            if self.current_phase == InterviewPhase.DEEP_DIVE and self.current_question_index < len(self.questions):
                q = self.questions[self.current_question_index]
                repeat_text = f"Sure, let me repeat the question: {q['question_text']}"
                q_id = q.get("id")
            elif self.current_phase == InterviewPhase.SELF_INTRO:
                repeat_text = f"Sure—please tell me briefly about yourself and your background in {self.role_title}."
                q_id = None
            else:
                repeat_text = self.last_ai_speech or "Are you ready to begin?"
                q_id = None

            self.last_ai_speech = repeat_text
            await self.persist_turn(
                turn_type=TurnType.CLARIFICATION.value,
                speaker="ai",
                text=repeat_text,
                question_id=q_id,
            )
            await self.emit_ui_state(
                "ai-speech-transcript",
                {"text": repeat_text, "phase": self.current_phase.value},
            )
            await self.push_frame(TTSSpeakFrame(repeat_text))
            return repeat_text

    def _reset_silence_timer(self, hold_extension: float = 0.0) -> None:
        self._last_activity_monotonic = time.monotonic()
        self._hold_extension_secs = hold_extension
        if hold_extension == 0.0:
            self._silence_nudge_count = 0

    def _start_silence_monitor(self) -> None:
        if not self.enable_silence_monitor:
            return
        if self._silence_task and not self._silence_task.done():
            return
        self._silence_task = asyncio.create_task(self._silence_monitor_loop())

    async def _silence_monitor_loop(self) -> None:
        """Checks for candidate silence (~8s nudge, ~20s rephrase offer, max 2 nudges, zero-audio mic check)."""
        try:
            while not self.is_completed:
                await asyncio.sleep(1.0)
                if not self.has_begun or self.is_completed or self.is_speaking or self.is_thinking:
                    self._last_activity_monotonic = time.monotonic()
                    continue
                if self._silence_nudge_count >= 2:
                    continue

                elapsed = time.monotonic() - self._last_activity_monotonic - self._hold_extension_secs
                threshold = 8.0 if self._silence_nudge_count == 0 else 20.0
                if elapsed < threshold:
                    continue

                async with self.lock:
                    if self.is_speaking or self.is_thinking or self.is_completed:
                        continue
                    self._silence_nudge_count += 1
                    self._last_activity_monotonic = time.monotonic()

                    # Zero-audio mic check on first silence timeout if no audio frames arrived
                    if self._silence_nudge_count == 1 and self._audio_segments_received_fn() == 0:
                        nudge_text = (
                            "I'm not hearing any audio from your microphone. "
                            "Please check if your mic is muted or select another input device."
                        )
                    elif self._silence_nudge_count == 1:
                        nudge_text = "Take your time—whenever you're ready, feel free to share your thoughts."
                    else:
                        nudge_text = "Would you like me to rephrase the question or approach it from a different angle?"

                    curr_q = (
                        self.questions[self.current_question_index]
                        if (self.current_phase == InterviewPhase.DEEP_DIVE and self.current_question_index < len(self.questions))
                        else None
                    )
                    await self.persist_turn(
                        turn_type=TurnType.SILENCE_NUDGE.value,
                        speaker="ai",
                        text=nudge_text,
                        question_id=curr_q.get("id") if curr_q else None,
                    )
                    await self.emit_ui_state(
                        "ai-speech-transcript",
                        {"text": nudge_text, "phase": self.current_phase.value, "is_nudge": True},
                    )
                    await self.push_frame(TTSSpeakFrame(nudge_text))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug(f"Silence monitor notice: {exc}")

    async def _persist_session_progress(self) -> None:
        try:
            async with AsyncSessionLocal() as db:
                s_row = (
                    await db.execute(select(InterviewSession).where(InterviewSession.id == self.session_id))
                ).scalars().first()
                if s_row:
                    s_row.current_phase = self.current_phase.value
                    s_row.current_question_index = self.current_question_index
                    s_row.running_summary = self.running_summary
                    if self.current_question_index < len(self.questions):
                        s_row.follow_up_count_in_current = int(
                            self.questions[self.current_question_index].get("follow_up_count", 0)
                        )
                    if self.is_blueprint_session and self.skill_sections:
                        rt = dict(s_row.runtime_state or {})
                        rt["section_index"] = self.current_skill_section_index
                        rt["sections"] = {
                            s["section_id"]: {
                                "skill_name": s["skill_name"],
                                "priority_tier": s.get("priority_tier", "P0"),
                                "exit_reason": s.get("exit_reason", "in_progress"),
                            }
                            for s in self.skill_sections
                        }
                        rt["probe_traces"] = list(self.section_state.get("probe_traces", []))
                        s_row.runtime_state = rt
                    await db.commit()
        except Exception as exc:
            logger.debug(f"Session progress persist notice: {exc}")

    async def _persist_question_progress(self, q_dict: Dict[str, Any]) -> None:
        q_id = q_dict.get("id")
        if not q_id:
            return
        try:
            async with AsyncSessionLocal() as db:
                q_row = (
                    await db.execute(select(InterviewQuestion).where(InterviewQuestion.id == q_id))
                ).scalars().first()
                if q_row:
                    q_row.follow_up_count = int(q_dict.get("follow_up_count", 0))
                    q_row.candidate_answer_transcript = q_dict.get("candidate_answer_transcript")
                    q_row.question_state = q_dict.get("question_state", "in_progress")
                    q_row.coverage_status = q_dict.get("coverage_status", {})
                    q_row.evidence_turn_ids = q_dict.get("evidence_turn_ids", [])
                    await db.commit()
        except Exception as exc:
            logger.debug(f"Question progress persist notice: {exc}")

    def _remaining_questions_by_priority(self) -> dict[str, int]:
        counts = {"P0": 0, "P1": 0, "P2": 0}
        for i in range(self.current_question_index + 1, len(self.questions)):
            tier = (self.questions[i].get("priority_tier") or "P0").upper()
            counts[tier] = counts.get(tier, 0) + 1
        return counts

    async def _persist_decision_coverage(
        self,
        session_id: str,
        section_id: str,
        coverage_updates: list[dict[str, Any]],
        turn_id: str,
    ) -> None:
        """Persist structured decision coverage updates directly to session_expectation_coverage table."""
        if not coverage_updates:
            return
        try:
            from backend.app.models import SessionExpectationCoverage
            async with AsyncSessionLocal() as db:
                for item in coverage_updates:
                    exp_id = item.get("expectation_id")
                    if not exp_id:
                        continue
                    status = item.get("status", "not_probed")
                    quote = item.get("quote")

                    stmt = select(SessionExpectationCoverage).where(
                        SessionExpectationCoverage.session_id == session_id,
                        SessionExpectationCoverage.expectation_id == exp_id,
                    )
                    res = await db.execute(stmt)
                    cov = res.scalars().first()
                    if not cov:
                        cov = SessionExpectationCoverage(
                            session_id=session_id,
                            expectation_id=exp_id,
                            status=status,
                            evidence_turn_ids=[turn_id] if turn_id else [],
                            evidence_quote=quote,
                        )
                        db.add(cov)
                    else:
                        if status in ("covered", "demonstrated"):
                            cov.status = status
                        elif status in ("partial", "probed") and cov.status not in ("covered", "demonstrated"):
                            cov.status = status
                        if quote:
                            cov.evidence_quote = quote
                        ev_ids = list(cov.evidence_turn_ids or [])
                        if turn_id and turn_id not in ev_ids:
                            ev_ids.append(turn_id)
                            cov.evidence_turn_ids = ev_ids
                await db.commit()
        except Exception as exc:
            logger.debug(f"Failed to persist decision coverage: {exc}")

    async def _handle_blueprint_candidate_answer(
        self,
        cleaned: str,
        cand_turn: InterviewTranscriptTurn,
        curr_turn_id: Optional[int] = None,
    ):
        """Execute the sectioned live delivery state machine (Checkpoint R3.4)."""
        if self.current_phase in (InterviewPhase.CLOSING, InterviewPhase.COMPLETED):
            return

        # Phase 1: WELCOME / READY_CHECK -> Phase 2: INTRO
        if self.current_phase in (InterviewPhase.GREETING, InterviewPhase.READY_CHECK):
            self.current_phase = InterviewPhase.SELF_INTRO
            intro_text = "Tell me briefly about yourself and what you've been working on lately."
            self.last_ai_speech = intro_text
            await self.persist_turn(
                turn_type=TurnType.SELF_INTRO_PROMPT.value,
                speaker="ai",
                text=intro_text,
                question_id=self.intro_question.get("id") if self.intro_question else None,
            )
            await self._persist_session_progress()
            await self.emit_ui_state("interview-phase-change", {"phase": InterviewPhase.SELF_INTRO.value, "text": intro_text})
            await self.emit_ui_state("ai-speech-transcript", {"text": intro_text, "phase": InterviewPhase.SELF_INTRO.value})
            await self.push_frame(TTSSpeakFrame(intro_text))
            return

        # Phase 2: INTRO -> Phase 3: SKILL SECTIONS
        if self.current_phase == InterviewPhase.SELF_INTRO:
            # At most one follow-up (may use intro_hook as a follow-up QUESTION after candidate's intro)
            if self.intro_followup_count == 0:
                self.intro_followup_count += 1
                hook_raw = (self.intro_question.get("question_text") if self.intro_question else "") or ""
                if hook_raw and not hook_raw.lower().startswith("tell me briefly"):
                    hook_clean = hook_raw.strip().rstrip("?.")
                    for prefix in ("i noticed that", "i noticed", "i saw that", "i saw", "i see that", "i see", "on your resume, you noted", "on your resume"):
                        if hook_clean.lower().startswith(prefix):
                            hook_clean = hook_clean[len(prefix):].strip()
                            break
                    # Strip any trailing question clause if it already has one
                    if ";" in hook_clean:
                        hook_clean = hook_clean.split(";")[0].strip()
                    if re.search(r"\b(what|how|why|could you|can you|tell me)\b", hook_clean, re.IGNORECASE):
                        # Extract the topic if it was phrased as "I saw X; what did you do?"
                        q_match = re.search(r"^(.*?)(?:;\s*|\s+)(what|how|why|could you|can you|tell me)\b.*$", hook_clean, re.IGNORECASE)
                        if q_match and q_match.group(1).strip():
                            topic = q_match.group(1).strip()
                            followup_text = f"I noticed {topic}; what was your part in that?"
                        else:
                            followup_text = f"{hook_clean}?"
                    else:
                        followup_text = f"I noticed {hook_clean}; what was your part in that?"
                else:
                    followup_text = "Could you tell me a bit more about a recent technical project you worked on and what your specific part was in that?"
                self.last_ai_speech = followup_text
                await self.persist_turn(
                    turn_type=TurnType.FOLLOW_UP.value,
                    speaker="ai",
                    text=followup_text,
                )
                await self.emit_ui_state("ai-speech-transcript", {"text": followup_text, "phase": InterviewPhase.SELF_INTRO.value})
                await self.push_frame(TTSSpeakFrame(followup_text))
                return

            # Bridge line into technical sections
            self.current_phase = InterviewPhase.DEEP_DIVE
            self.current_skill_section_index = 0

            if not self.skill_sections:
                await self.move_to_candidate_questions(ack_prefix="Thanks, that's clear.")
                return

            sec = self.skill_sections[0]
            topic_label = sec.get("spoken_topic_label") or sec["skill_name"]
            trans_line = f"Thanks, that's clear. Let's begin with our first section: {topic_label}."
            anchor_text = sec["anchor_q"]["question_text"] if sec.get("anchor_q") else "Could you walk me through your experience?"
            combined_spoken = f"{trans_line} {anchor_text}".strip()

            self.last_ai_speech = combined_spoken
            self.section_state["current_section_phase"] = "anchor"
            self.section_state["used_anchor_alt"] = False
            self.section_state["asked_probe_ids"] = set()
            self.section_state["asked_escalation"] = False
            self.section_state["section_started_monotonic"] = time.monotonic()

            await self.persist_turn(
                turn_type="anchor",
                speaker="ai",
                text=combined_spoken,
                question_id=sec.get("anchor_q", {}).get("id"),
            )
            await self._persist_session_progress()
            await self.emit_ui_state("interview-progress", {
                "section_index": 0,
                "total_sections": len(self.skill_sections),
                "skill_name": sec["skill_name"],
            })
            await self.emit_ui_state("ai-speech-transcript", {
                "text": combined_spoken,
                "phase": InterviewPhase.DEEP_DIVE.value,
            })
            await self.push_frame(TTSSpeakFrame(combined_spoken))
            return

        # Phase 5: CANDIDATE QUESTIONS -> Phase 6: CLOSING
        if self.current_phase == InterviewPhase.CANDIDATE_QUESTIONS:
            cleaned_lower = cleaned.lower()
            if any(tok in cleaned_lower for tok in ("no question", "nothing", "i'm good", "no more", "that's all", "that is all", "nope", "none")):
                await self.move_to_closing()
                return

            self.candidate_qa_count += 1
            ans = await answer_candidate_closing_question(cleaned, self.job_public_fields)
            if self.candidate_qa_count < 3:
                ans_spoken = f"{ans} Do you have any other questions for me?"
            else:
                ans_spoken = ans

            self.last_ai_speech = ans_spoken
            await self.persist_turn(
                turn_type=TurnType.CLARIFICATION.value,
                speaker="ai",
                text=ans_spoken,
            )
            await self.emit_ui_state("ai-speech-transcript", {
                "text": ans_spoken,
                "phase": InterviewPhase.CANDIDATE_QUESTIONS.value,
            })
            await self.push_frame(TTSSpeakFrame(ans_spoken))
            return

        # Phase 3: SKILL SECTIONS (InterviewPhase.DEEP_DIVE)
        if self.current_phase == InterviewPhase.DEEP_DIVE:
            if self.current_skill_section_index >= len(self.skill_sections):
                await self.move_to_candidate_questions()
                return

            sec = self.skill_sections[self.current_skill_section_index]
            elapsed = time.monotonic() - self.section_state["section_started_monotonic"]
            alloc_mins = float(sec.get("allocated_minutes", 4.0) or 4.0)
            time_left_secs = max(0.0, (alloc_mins * 60.0) - elapsed)

            streamed_sentences: list[str] = []
            async def _on_sentence_chunk(sentence: str):
                streamed_sentences.append(sentence)
                await self.push_frame(TTSSpeakFrame(sentence))

            unasked_probes = [
                p for p in sec.get("probes", [])
                if p.get("id") not in self.section_state["asked_probe_ids"]
            ]
            resume_p = sec.get("resume_probe")
            if resume_p and resume_p.get("id") in self.section_state["asked_probe_ids"]:
                resume_p = None

            decision = await stream_section_turn_decision(
                section_name=sec["skill_name"],
                priority_tier=sec.get("priority_tier", "P0"),
                time_left_secs=time_left_secs,
                candidate_answer=cleaned,
                expectations=sec.get("expectations", []),
                available_probes=unasked_probes,
                resume_probe=resume_p,
                candidate_resume_notes=sec.get("resume_notes", ""),
                recent_dialogue=self.recent_turns,
                turn_index=self.current_turn_sequence,
                on_sentence=_on_sentence_chunk,
            )

            # Check for stale turn commit (if candidate spoke again while decision was running)
            if curr_turn_id is not None and curr_turn_id != self._active_turn_id:
                logger.info("Dropping stale decision result: turn %s != active %s", curr_turn_id, self._active_turn_id)
                return

            self._pending_llm_ttft_ms = decision.llm_ttft_ms

            # Persist coverage updates directly from single structured decision
            if decision.coverage_updates:
                asyncio.create_task(
                    self._persist_decision_coverage(
                        self.session_id,
                        sec["section_id"],
                        decision.coverage_updates,
                        cand_turn.id,
                    )
                )
            else:
                asyncio.create_task(
                    update_section_expectation_coverage_async(
                        self.session_id,
                        sec["section_id"],
                        cleaned,
                        cand_turn.id,
                    )
                )

            # Log decision in session trace
            if self.session_trace:
                toks = decision.tokens or {}
                self.session_trace.log_decision(
                    turn_id=str(curr_turn_id or self._active_turn_id),
                    action=decision.action,
                    decision_json={
                        "control_token": decision.control_token,
                        "selected_probe_id": decision.selected_probe_id,
                        "reasoning": decision.reasoning,
                        "spoken_reply": decision.spoken_reply,
                        "coverage_count": len(decision.coverage_updates),
                    },
                    provider=decision.provider or "gemini",
                    model=decision.model_name or "gemini-2.5-flash",
                    latency_ms=decision.llm_ttft_ms or 0.0,
                    prompt_tokens=toks.get("prompt", 0),
                    thinking_tokens=toks.get("thinking", 0),
                    completion_tokens=toks.get("completion", 0),
                    degraded=decision.degraded,
                )

            if decision.is_injection:
                await self.log_integrity_event(
                    event_type="prompt_injection",
                    details_json={"candidate_text": cleaned[:300], "reason": decision.reasoning},
                    turn_id=cand_turn.id,
                )

            # Handle REPEAT
            if decision.action == "repeat":
                repeat_text = f"Sure, let me repeat that: {self.last_ai_speech}"
                self.last_ai_speech = repeat_text
                await self.persist_turn(
                    turn_type=TurnType.CLARIFICATION.value,
                    speaker="ai",
                    text=repeat_text,
                    llm_ttft_ms=decision.llm_ttft_ms,
                    provider=decision.provider,
                    model_name=decision.model_name,
                )
                await self.emit_ui_state("ai-speech-transcript", {"text": repeat_text, "phase": InterviewPhase.DEEP_DIVE.value})
                await self.push_frame(TTSSpeakFrame(repeat_text))
                return

            # Handle HOLD
            if decision.action == "hold":
                self._reset_silence_timer(hold_extension=15.0)
                hold_reply = decision.spoken_reply or "Of course, take a moment."
                self.last_ai_speech = hold_reply
                await self.persist_turn(
                    turn_type=TurnType.CLARIFICATION.value,
                    speaker="ai",
                    text=hold_reply,
                    llm_ttft_ms=decision.llm_ttft_ms,
                    provider=decision.provider,
                    model_name=decision.model_name,
                )
                await self.emit_ui_state("ai-speech-transcript", {"text": hold_reply, "phase": InterviewPhase.DEEP_DIVE.value})
                if not streamed_sentences:
                    await self.push_frame(TTSSpeakFrame(hold_reply))
                return

            # Handle CLARIFY
            if decision.action == "clarify":
                clarify_reply = decision.spoken_reply or "Could you clarify that?"
                self.last_ai_speech = clarify_reply
                await self.persist_turn(
                    turn_type=TurnType.CLARIFICATION.value,
                    speaker="ai",
                    text=clarify_reply,
                    llm_ttft_ms=decision.llm_ttft_ms,
                    provider=decision.provider,
                    model_name=decision.model_name,
                )
                await self.emit_ui_state("ai-speech-transcript", {"text": clarify_reply, "phase": InterviewPhase.DEEP_DIVE.value})
                if not streamed_sentences:
                    await self.push_frame(TTSSpeakFrame(clarify_reply))
                return

            # Handle NO_EXPERIENCE
            if decision.action == "no_experience":
                alt_q = sec.get("anchor_alt_q")
                if alt_q and not self.section_state["used_anchor_alt"]:
                    self.section_state["used_anchor_alt"] = True
                    alt_spoken = f"No problem at all! Let's approach it from a different angle: {alt_q['question_text']}"
                    self.last_ai_speech = alt_spoken
                    await self.persist_turn(
                        turn_type="anchor_alt",
                        speaker="ai",
                        text=alt_spoken,
                        question_id=alt_q.get("id"),
                        llm_ttft_ms=decision.llm_ttft_ms,
                        provider=decision.provider,
                        model_name=decision.model_name,
                    )
                    await self.emit_ui_state("ai-speech-transcript", {"text": alt_spoken, "phase": InterviewPhase.DEEP_DIVE.value})
                    await self.push_frame(TTSSpeakFrame(alt_spoken))
                    return
                else:
                    await self._advance_to_next_blueprint_section(prefix_ack="No problem at all, let's move forward.", exit_reason="depth_cap")
                    return

            # Record server-side probe trace per R3.1 Requirement 5
            if decision.action in ("probe", "free_probe", "enough"):
                self.section_state.setdefault("probe_traces", []).append({
                    "section_index": self.current_skill_section_index,
                    "skill_name": sec.get("skill_name"),
                    "action": decision.action,
                    "selected_probe_id": decision.selected_probe_id,
                    "reasoning": decision.reasoning,
                    "timestamp": time.time(),
                })

            # Handle PROBE
            if decision.action == "probe":
                probe_id = decision.selected_probe_id
                probe_obj = next((p for p in sec.get("probes", []) if p.get("id") == probe_id), None)
                is_resume = False
                if not probe_obj and resume_p and resume_p.get("id") == probe_id:
                    probe_obj = resume_p
                    is_resume = True

                if probe_obj:
                    self.section_state["asked_probe_ids"].add(probe_obj["id"])
                    probe_text = probe_obj["question_text"]
                    self.last_ai_speech = probe_text
                    turn_kind = "resume_probe" if is_resume else "probe"
                    await self.persist_turn(
                        turn_type=turn_kind,
                        speaker="ai",
                        text=probe_text,
                        question_id=probe_obj.get("id"),
                        llm_ttft_ms=decision.llm_ttft_ms,
                        provider=decision.provider,
                        model_name=decision.model_name,
                    )
                    await self.emit_ui_state("ai-speech-transcript", {"text": probe_text, "phase": InterviewPhase.DEEP_DIVE.value})
                    if not streamed_sentences:
                        await self.push_frame(TTSSpeakFrame(probe_text))
                    return
                else:
                    reply = decision.spoken_reply or "Could you share more about the specific technical choices you made?"
                    self.last_ai_speech = reply
                    await self.persist_turn(
                        turn_type="probe",
                        speaker="ai",
                        text=reply,
                        llm_ttft_ms=decision.llm_ttft_ms,
                        provider=decision.provider,
                        model_name=decision.model_name,
                    )
                    await self.emit_ui_state("ai-speech-transcript", {"text": reply, "phase": InterviewPhase.DEEP_DIVE.value})
                    if not streamed_sentences:
                        await self.push_frame(TTSSpeakFrame(reply))
                    return

            # Handle FREE_PROBE
            if decision.action == "free_probe":
                reply = decision.spoken_reply or "Could you elaborate on the key trade-offs in that approach?"
                self.last_ai_speech = reply
                await self.persist_turn(
                    turn_type="probe",
                    speaker="ai",
                    text=reply,
                    llm_ttft_ms=decision.llm_ttft_ms,
                    provider=decision.provider,
                    model_name=decision.model_name,
                )
                await self.emit_ui_state("ai-speech-transcript", {"text": reply, "phase": InterviewPhase.DEEP_DIVE.value})
                if not streamed_sentences:
                    await self.push_frame(TTSSpeakFrame(reply))
                return

            # Handle ENOUGH
            if decision.action == "enough":
                esc_q = sec.get("escalation_q")
                if esc_q and not self.section_state["asked_escalation"] and time_left_secs >= 45.0:
                    self.section_state["asked_escalation"] = True
                    esc_text = esc_q["question_text"]
                    prefix = decision.spoken_reply or pick_varied_ack(self.current_turn_sequence)
                    full_esc = f"{prefix} {esc_text}".strip()
                    self.last_ai_speech = full_esc
                    await self.persist_turn(
                        turn_type="escalation",
                        speaker="ai",
                        text=full_esc,
                        question_id=esc_q.get("id"),
                        llm_ttft_ms=decision.llm_ttft_ms,
                        provider=decision.provider,
                        model_name=decision.model_name,
                    )
                    await self.emit_ui_state("ai-speech-transcript", {"text": full_esc, "phase": InterviewPhase.DEEP_DIVE.value})
                    if streamed_sentences:
                        await self.push_frame(TTSSpeakFrame(esc_text))
                    else:
                        await self.push_frame(TTSSpeakFrame(full_esc))
                    return
                else:
                    esc_reason = "time" if time_left_secs <= 0 else "core_covered"
                    await self._advance_to_next_blueprint_section(
                        prefix_ack=decision.spoken_reply if not streamed_sentences else "",
                        exit_reason=esc_reason,
                    )
                    return

    async def _advance_to_next_blueprint_section(self, prefix_ack: str = "", exit_reason: str = "core_covered"):
        """Advance section pointer and announce section transition or wrap (R3.4 Phase 3/4)."""
        if 0 <= self.current_skill_section_index < len(self.skill_sections):
            cur_sec = self.skill_sections[self.current_skill_section_index]
            p_tier = (cur_sec.get("priority_tier") or "P0").upper()
            if exit_reason == "skipped" and p_tier == "P0":
                raise ValueError(f"Mandatory P0 section '{cur_sec.get('skill_name')}' cannot be skipped without a time reason!")
            cur_sec["exit_reason"] = exit_reason
            logger.info("Section '%s' exited with reason: %s", cur_sec.get("skill_name"), exit_reason)

        self.current_skill_section_index += 1
        if self.current_skill_section_index < len(self.skill_sections):
            next_sec = self.skill_sections[self.current_skill_section_index]
            is_last_skill = (self.current_skill_section_index == len(self.skill_sections) - 1)

            # Reset section state for new section
            self.section_state["current_section_phase"] = "anchor"
            self.section_state["used_anchor_alt"] = False
            self.section_state["asked_probe_ids"] = set()
            self.section_state["asked_escalation"] = False
            self.section_state["section_started_monotonic"] = time.monotonic()

            # Phase 4 Time announcement if this is the final skill section
            topic_label = next_sec.get("spoken_topic_label") or next_sec["skill_name"]
            anchor_text = next_sec["anchor_q"]["question_text"] if next_sec.get("anchor_q") else ""

            # Ensure at most one neutral bridge max per transition and no evaluative phrasing
            clean_bridge = ""
            if prefix_ack:
                if any(ev in prefix_ack.lower() for ev in ("great", "excellent", "good", "perfect", "awesome")):
                    clean_bridge = "Thanks, that's clear."
                else:
                    clean_bridge = prefix_ack.strip()

            if is_last_skill:
                rem_mins = max(1.0, round(self.pacing.remaining_seconds() / 60.0))
                if rem_mins <= 10.0:
                    announcement = f"We have about {int(rem_mins)} minutes remaining, so let's move to our final technical section: {topic_label}."
                else:
                    announcement = f"Let's move to our final technical section: {topic_label}."
                spoken = f"{clean_bridge} {announcement} {anchor_text}".strip()
            else:
                if clean_bridge:
                    spoken = f"{clean_bridge} Moving on to our next section: {topic_label}. {anchor_text}".strip()
                else:
                    spoken = f"Let's move on to our next section: {topic_label}. {anchor_text}".strip()

            self.last_ai_speech = spoken
            await self.persist_turn(
                turn_type="anchor",
                speaker="ai",
                text=spoken,
                question_id=next_sec.get("anchor_q", {}).get("id"),
            )
            await self._persist_session_progress()
            await self.emit_ui_state("interview-progress", {
                "section_index": self.current_skill_section_index,
                "total_sections": len(self.skill_sections),
                "skill_name": next_sec["skill_name"],
            })
            await self.emit_ui_state("ai-speech-transcript", {
                "text": spoken,
                "phase": InterviewPhase.DEEP_DIVE.value,
            })
            await self.push_frame(TTSSpeakFrame(spoken))
        else:
            # Completed all skill sections -> move to Phase 5 Candidate Questions!
            await self.move_to_candidate_questions(ack_prefix=prefix_ack)

    async def handle_candidate_answer(self, candidate_text: str, turn_id: Optional[int] = None):
        """Processes candidate STT transcription and advances conversation flow with streaming decisions."""
        cleaned = (candidate_text or "").strip()
        if not cleaned:
            return

        if turn_id is not None and turn_id != self._active_turn_id:
            logger.info("Dropping stale candidate answer commit: turn %s != active %s", turn_id, self._active_turn_id)
            return

        # Combine with any merged partial turn if candidate paused & resumed before bot audio started
        if self._merge_buffer:
            cleaned = f"{self._merge_buffer} {cleaned}".strip()
            self._merge_buffer = ""

        async with self.lock:
            self._reset_silence_timer()
            self._turn_confirmed_monotonic = time.perf_counter()
            self._awaiting_first_bot_audio = True
            self._pending_llm_ttft_ms = 0.0
            self.is_thinking = True
            await self.emit_ui_state("interview-bot-state", {"state": "thinking"})

            logger.info(f"Handling candidate answer in phase {self.current_phase.value}: '{cleaned}'")

            curr_q = (
                self.questions[self.current_question_index]
                if (self.current_phase == InterviewPhase.DEEP_DIVE and self.current_question_index < len(self.questions))
                else None
            )
            q_id = curr_q.get("id") if curr_q else None

            self.last_candidate_speech = cleaned
            await self.emit_ui_state(
                "candidate-speech-transcript",
                {"text": cleaned},
            )
            cand_turn = await self.persist_turn(
                turn_type=(
                    TurnType.CANDIDATE_QUESTION.value
                    if self.current_phase == InterviewPhase.CANDIDATE_QUESTIONS
                    else TurnType.CANDIDATE_ANSWER.value
                ),
                speaker="candidate",
                text=cleaned,
                question_id=q_id,
                confidence=self._last_stt_confidence,
                stt_final_ms=self._last_stt_final_ms,
            )
            self._active_candidate_turn_id = cand_turn.id

            # Section state machine branch for Blueprint Sessions (Checkpoint R3.4)
            if self.is_blueprint_session:
                await self._handle_blueprint_candidate_answer(cleaned, cand_turn, curr_turn_id=turn_id)
                return

            # Phase: READY_CHECK -> SELF_INTRO (or directly DEEP_DIVE if candidate already gave long intro)
            if self.current_phase in (InterviewPhase.GREETING, InterviewPhase.READY_CHECK):
                if len(cleaned.split()) >= 20:
                    # Candidate jumped straight into introducing themselves
                    self.current_phase = InterviewPhase.SELF_INTRO
                else:
                    self.current_phase = InterviewPhase.SELF_INTRO
                    intro_text = (
                        f"Great! To get started, please tell me a bit about yourself and your relevant background in {self.role_title}."
                    )
                    self.last_ai_speech = intro_text
                    await self.persist_turn(
                        turn_type=TurnType.SELF_INTRO_PROMPT.value,
                        speaker="ai",
                        text=intro_text,
                    )
                    await self._persist_session_progress()
                    await self.emit_ui_state(
                        "interview-phase-change",
                        {"phase": InterviewPhase.SELF_INTRO.value, "text": intro_text},
                    )
                    await self.emit_ui_state(
                        "ai-speech-transcript",
                        {"text": intro_text, "phase": InterviewPhase.SELF_INTRO.value},
                    )
                    await self.push_frame(TTSSpeakFrame(intro_text))
                    return

            # Phase: SELF_INTRO -> DEEP_DIVE
            if self.current_phase == InterviewPhase.SELF_INTRO:
                self.current_phase = InterviewPhase.DEEP_DIVE
                self.current_question_index = 0
                self.in_followup = False
                self.pacing.mark_question_started()

                if self.questions:
                    q = self.questions[0]
                    q["question_state"] = QuestionState.IN_PROGRESS.value
                    await self._persist_question_progress(q)
                    intro_ack = "Thank you for sharing your background. Let's dive into our technical questions."
                    q_text = f"{intro_ack} {q['question_text']}"
                    self.last_ai_speech = q_text
                    await self.persist_turn(
                        turn_type=TurnType.MAIN_QUESTION.value,
                        speaker="ai",
                        text=q_text,
                        question_id=q.get("id"),
                    )
                    await self._persist_session_progress()
                    await self.emit_ui_state(
                        "interview-progress",
                        {
                            "question_index": 0,
                            "total_questions": len(self.questions),
                            "question_text": q["question_text"],
                            "skill_name": q.get("skill_name"),
                        },
                    )
                    await self.emit_ui_state(
                        "ai-speech-transcript",
                        {"text": q_text, "question_text": q["question_text"], "phase": InterviewPhase.DEEP_DIVE.value},
                    )
                    await self.push_frame(TTSSpeakFrame(q_text))
                else:
                    await self.move_to_candidate_questions()
                return

            # Phase: CANDIDATE_QUESTIONS -> CLOSING
            if self.current_phase == InterviewPhase.CANDIDATE_QUESTIONS:
                answer_text = await answer_candidate_closing_question(cleaned, self.job_public_fields)
                await self.move_to_closing(prefix_answer=answer_text)
                return

            # Phase: DEEP_DIVE
            if self.current_phase == InterviewPhase.DEEP_DIVE:
                curr_q = self.questions[self.current_question_index]
                f_count = int(curr_q.get("follow_up_count", 0))
                max_depth = min(int(curr_q.get("follow_up_depth_allowed", 1)), self.max_followup_depth)

                # Update evidence coverage & transcript on current question
                prev_ans = curr_q.get("candidate_answer_transcript") or ""
                curr_q["candidate_answer_transcript"] = (f"{prev_ans}\n{cleaned}".strip() if prev_ans else cleaned)
                ev_ids = list(curr_q.get("evidence_turn_ids") or [])
                if cand_turn.id not in ev_ids:
                    ev_ids.append(cand_turn.id)
                curr_q["evidence_turn_ids"] = ev_ids
                curr_q["coverage_status"] = update_coverage_status(
                    curr_q.get("expected_key_points") or [],
                    curr_q.get("coverage_status") or {},
                    curr_q["candidate_answer_transcript"],
                )

                allow_followup = self.pacing.should_allow_followup(
                    current_priority=curr_q.get("priority_tier") or "P0",
                    skill_name=curr_q.get("skill_name"),
                    remaining_questions_by_priority=self._remaining_questions_by_priority(),
                    total_questions=len(self.questions),
                )

                self.is_thinking = True
                await self.emit_ui_state("interview-bot-state", {"state": "thinking"})

                streamed_sentences: list[str] = []

                async def _on_sentence_chunk(sentence: str):
                    # Stream follow-up/clarify/redirect sentences to TTS as soon as sentence boundary arrives!
                    streamed_sentences.append(sentence)
                    await self.push_frame(TTSSpeakFrame(sentence))

                decision = await stream_turn_decision(
                    interviewer_brief=self.interviewer_brief,
                    question_text=curr_q["question_text"],
                    skill_name=curr_q.get("skill_name") or "Technical",
                    priority_tier=curr_q.get("priority_tier") or "P0",
                    expected_key_points=curr_q.get("expected_key_points") or [],
                    coverage_status=curr_q.get("coverage_status") or {},
                    candidate_answer=cleaned,
                    follow_up_count=f_count,
                    follow_up_depth_allowed=max_depth,
                    allow_followup_by_pacing=allow_followup,
                    running_summary=self.running_summary,
                    recent_turns=self.recent_turns,
                    turn_index=self.current_turn_sequence,
                    on_sentence=_on_sentence_chunk,
                )
                self.is_thinking = False
                self._pending_llm_ttft_ms = decision.llm_ttft_ms

                if decision.is_injection:
                    await self.log_integrity_event(
                        event_type="prompt_injection",
                        details_json={"candidate_text": cleaned[:300], "reason": decision.reasoning},
                        turn_id=cand_turn.id,
                    )

                # Handle REPEAT without incrementing follow_up_count
                if decision.action == "repeat":
                    repeat_reply = f"Sure, let me repeat that: {curr_q['question_text']}"
                    self.last_ai_speech = repeat_reply
                    await self.persist_turn(
                        turn_type=TurnType.CLARIFICATION.value,
                        speaker="ai",
                        text=repeat_reply,
                        question_id=curr_q.get("id"),
                    )
                    await self.emit_ui_state(
                        "ai-speech-transcript",
                        {"text": repeat_reply, "question_text": curr_q["question_text"], "phase": InterviewPhase.DEEP_DIVE.value},
                    )
                    await self.push_frame(TTSSpeakFrame(repeat_reply))
                    return

                # Handle HOLD ("give me a moment") without incrementing follow_up_count
                if decision.action == "hold":
                    self._reset_silence_timer(hold_extension=15.0)
                    hold_reply = decision.spoken_reply or "Of course, take a moment."
                    self.last_ai_speech = hold_reply
                    await self.persist_turn(
                        turn_type=TurnType.CLARIFICATION.value,
                        speaker="ai",
                        text=hold_reply,
                        question_id=curr_q.get("id"),
                    )
                    await self.emit_ui_state(
                        "ai-speech-transcript",
                        {"text": hold_reply, "phase": InterviewPhase.DEEP_DIVE.value},
                    )
                    if not streamed_sentences:
                        await self.push_frame(TTSSpeakFrame(hold_reply))
                    return

                # Handle CLARIFY or REDIRECT without consuming follow_up_count (unless repeated)
                if decision.action in ("clarify", "redirect"):
                    reply_text = decision.spoken_reply or curr_q["question_text"]
                    self.last_ai_speech = reply_text
                    await self.persist_turn(
                        turn_type=TurnType.CLARIFICATION.value,
                        speaker="ai",
                        text=reply_text,
                        question_id=curr_q.get("id"),
                    )
                    await self._persist_question_progress(curr_q)
                    await self.emit_ui_state(
                        "ai-speech-transcript",
                        {"text": reply_text, "phase": InterviewPhase.DEEP_DIVE.value},
                    )
                    if not streamed_sentences:
                        await self.push_frame(TTSSpeakFrame(reply_text))
                    return

                # Handle FOLLOWUP
                if decision.action == "follow_up" and decision.follow_up_question:
                    self.in_followup = True
                    curr_q["follow_up_count"] = f_count + 1
                    curr_q["question_state"] = QuestionState.FOLLOW_UP.value
                    await self._persist_question_progress(curr_q)
                    await self._persist_session_progress()

                    followup_text = decision.follow_up_question
                    self.last_ai_speech = followup_text
                    await self.persist_turn(
                        turn_type=TurnType.FOLLOW_UP.value,
                        speaker="ai",
                        text=followup_text,
                        question_id=curr_q.get("id"),
                    )
                    await self.emit_ui_state(
                        "interview-progress",
                        {
                            "question_index": self.current_question_index,
                            "total_questions": len(self.questions),
                            "is_followup": True,
                            "question_text": followup_text,
                            "skill_name": curr_q.get("skill_name"),
                        },
                    )
                    await self.emit_ui_state(
                        "ai-speech-transcript",
                        {"text": followup_text, "is_followup": True, "phase": InterviewPhase.DEEP_DIVE.value},
                    )
                    if not streamed_sentences:
                        await self.push_frame(TTSSpeakFrame(followup_text))
                    return

                # Handle ADVANCE -> mark current question answered, update running_summary, and pick next question via PacingController
                curr_q["question_state"] = QuestionState.ANSWERED.value
                await self._persist_question_progress(curr_q)

                summary_entry = f"Q{self.current_question_index + 1}({curr_q.get('skill_name')}): {cleaned[:110]}"
                self.running_summary = (
                    f"{self.running_summary} | {summary_entry}".strip(" |")[-600:]
                )
                self.in_followup = False

                next_idx, skipped_indices = self.pacing.select_next_question_index(
                    self.questions, self.current_question_index
                )
                for sk_idx in skipped_indices:
                    self.questions[sk_idx]["question_state"] = QuestionState.SKIPPED.value
                    await self._persist_question_progress(self.questions[sk_idx])

                if next_idx is not None and next_idx < len(self.questions):
                    self.current_question_index = next_idx
                    self.pacing.mark_question_started()
                    next_q = self.questions[self.current_question_index]
                    next_q["question_state"] = QuestionState.IN_PROGRESS.value
                    await self._persist_question_progress(next_q)
                    await self._persist_session_progress()

                    ack_prefix = (decision.spoken_reply or "").strip()
                    next_q_spoken = next_q["question_text"]
                    combined_next = f"{ack_prefix} {next_q_spoken}".strip() if ack_prefix else next_q_spoken
                    self.last_ai_speech = combined_next

                    await self.persist_turn(
                        turn_type=TurnType.MAIN_QUESTION.value,
                        speaker="ai",
                        text=combined_next,
                        question_id=next_q.get("id"),
                    )
                    await self.emit_ui_state(
                        "interview-progress",
                        {
                            "question_index": self.current_question_index,
                            "total_questions": len(self.questions),
                            "question_text": next_q_spoken,
                            "skill_name": next_q.get("skill_name"),
                        },
                    )
                    await self.emit_ui_state(
                        "ai-speech-transcript",
                        {"text": combined_next, "question_text": next_q_spoken, "phase": InterviewPhase.DEEP_DIVE.value},
                    )
                    # Note: if ack_prefix was already streamed via _on_sentence_chunk, only speak next_q_spoken!
                    if streamed_sentences:
                        await self.push_frame(TTSSpeakFrame(next_q_spoken))
                    else:
                        await self.push_frame(TTSSpeakFrame(combined_next))
                else:
                    await self.move_to_candidate_questions(ack_prefix=(decision.spoken_reply if not streamed_sentences else ""))

    async def move_to_candidate_questions(self, ack_prefix: str = ""):
        """Invite the candidate to ask any questions before final closing (Part B5)."""
        self.current_phase = InterviewPhase.CANDIDATE_QUESTIONS
        prompt_text = "Before we wrap up, do you have any questions for me about the role or team?"
        full_text = f"{ack_prefix} {prompt_text}".strip() if ack_prefix else prompt_text
        self.last_ai_speech = full_text

        await self.persist_turn(
            turn_type=TurnType.CLOSING.value,
            speaker="ai",
            text=full_text,
        )
        await self._persist_session_progress()
        await self.emit_ui_state(
            "interview-phase-change",
            {"phase": InterviewPhase.CANDIDATE_QUESTIONS.value, "text": full_text},
        )
        await self.emit_ui_state(
            "ai-speech-transcript",
            {"text": full_text, "phase": InterviewPhase.CANDIDATE_QUESTIONS.value},
        )
        await self.push_frame(TTSSpeakFrame(full_text))

    async def move_to_closing(self, prefix_answer: str = ""):
        """Final closing thank-you and next steps (Part B5)."""
        self.current_phase = InterviewPhase.CLOSING
        first_name = self.candidate_name.split()[0] if self.candidate_name else "Candidate"
        closing_core = (
            f"Thank you so much for your time and for sharing your experience today, {first_name}. "
            "Our recruiting team will review your interview and follow up with next steps soon. Have a great day!"
        )
        closing_text = f"{prefix_answer} {closing_core}".strip() if prefix_answer else closing_core
        self.last_ai_speech = closing_text
        await self.persist_turn(
            turn_type=TurnType.CLOSING.value,
            speaker="ai",
            text=closing_text,
        )
        await self._persist_session_progress()
        await self.emit_ui_state(
            "interview-phase-change",
            {"phase": InterviewPhase.CLOSING.value, "text": closing_text},
        )
        await self.emit_ui_state(
            "ai-speech-transcript",
            {"text": closing_text, "phase": InterviewPhase.CLOSING.value},
        )
        await self.push_frame(TTSSpeakFrame(closing_text))

        asyncio.create_task(self.mark_completed())

    async def mark_completed(self):
        """Marks the interview session completed in DB and triggers the Evidence-Anchored Judge (Part D1)."""
        await asyncio.sleep(3.5)
        async with self.lock:
            if self.is_completed:
                return
            self.is_completed = True
            self.current_phase = InterviewPhase.COMPLETED

            async with AsyncSessionLocal() as db:
                stmt = select(InterviewSession).where(InterviewSession.id == self.session_id)
                res = await db.execute(stmt)
                session = res.scalars().first()
                if session:
                    session.status = "completed"
                    session.current_phase = "completed"
                    session.running_summary = self.running_summary
                    session.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await db.commit()

            logger.info(f"Interview session {self.session_id} marked COMPLETED. Triggering post-interview Judge...")
            await self.emit_ui_state(
                "interview-phase-change",
                {"phase": InterviewPhase.COMPLETED.value, "status": "completed"},
            )
            asyncio.create_task(self._run_post_interview_judge())

    async def _run_post_interview_judge(self) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await evaluate_interview_session(self.session_id, db)
            logger.info(f"Post-interview evaluation completed for session {self.session_id}.")
        except Exception as exc:
            logger.error(f"Post-interview judge error for session {self.session_id}: {exc}")

    async def _mark_bot_turn_interrupted(self) -> None:
        """Record exact spoken prefix and was_interrupted=True when candidate barges in (Part B4)."""
        if not self._active_ai_turn_id or not self._active_ai_full_text:
            return
        turn_id = self._active_ai_turn_id
        full_text = self._active_ai_full_text
        elapsed = (
            max(0.2, time.monotonic() - self._active_ai_started_monotonic)
            if self._active_ai_started_monotonic
            else 1.0
        )
        # Estimate spoken words at ~3.2 words/sec
        words = full_text.split()
        spoken_word_count = max(1, min(len(words), int(elapsed * 3.2)))
        spoken_prefix = " ".join(words[:spoken_word_count])
        try:
            async with AsyncSessionLocal() as db:
                turn = (
                    await db.execute(select(InterviewTranscriptTurn).where(InterviewTranscriptTurn.id == turn_id))
                ).scalars().first()
                if turn:
                    turn.was_interrupted = True
                    turn.spoken_text = spoken_prefix
                    await db.commit()
        except Exception as exc:
            logger.debug(f"Interruption turn update notice: {exc}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        try:
            await super().process_frame(frame, direction)
        except Exception:
            pass

        if isinstance(frame, UserStartedSpeakingFrame):
            self._last_activity_monotonic = time.monotonic()
            self._candidate_speech_started_monotonic = time.monotonic()
            # If a turn commit was pending within merge window, cancel it so speech continues smoothly
            if self._commit_timer_task and not self._commit_timer_task.done():
                self._commit_timer_task.cancel()
                logger.info("Resumed speaking within merge window; cancelled pending turn commit.")
            # Turn merge (Part A6): if candidate resumes speaking before bot audio starts, merge turns
            if (self.is_thinking or self._awaiting_first_bot_audio) and self._active_turn_task and not self._active_turn_task.done():
                self._active_turn_task.cancel()
                self._merge_buffer = self.last_candidate_speech
                self.is_thinking = False
                self._awaiting_first_bot_audio = False
                logger.info(f"Turn merge: candidate resumed speaking before bot audio started; buffered: '{self._merge_buffer}'")

        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._candidate_speech_started_monotonic is not None:
                self._candidate_speech_duration = time.monotonic() - self._candidate_speech_started_monotonic
                self._candidate_speech_started_monotonic = None
            if self._accumulated_full_text:
                self._schedule_turn_commit()

        elif isinstance(frame, TranscriptionFrame):
            if frame.user_id == "candidate" and frame.text:
                self._last_activity_monotonic = time.monotonic()
                speech_text = frame.text.strip()
                if not speech_text:
                    return

                # If candidate spoke while bot was speaking (Barge-in handling)
                if self.is_speaking:
                    # 1. Backchannel filter: candidate backchannels ("yeah", "uh-huh") do not interrupt bot
                    if _is_backchannel(speech_text):
                        logger.info(f"Ignored candidate backchannel during bot speech: '{speech_text}'")
                        await self.emit_ui_state(
                            "candidate-speech-transcript",
                            {"text": speech_text, "is_backchannel": True},
                        )
                        return

                    # 2. Duration guard: minimum speech duration (>= 0.35s) before interruption counts
                    if self._candidate_speech_duration < MIN_INTERRUPTION_SPEECH_DURATION_SECS and len(speech_text.split()) <= 2:
                        logger.info(
                            f"Ignored transient noise/short echo during bot speech ({self._candidate_speech_duration:.2f}s): '{speech_text}'"
                        )
                        return

                    # Substantive interruption! Halt bot immediately:
                    logger.info(f"Substantive candidate barge-in ({self._candidate_speech_duration:.2f}s): '{speech_text}'")
                    await self._mark_bot_turn_interrupted()
                    self.is_speaking = False
                    await self.push_frame(InterruptionFrame(), direction)
                    await self.emit_ui_state("interview-bot-state", {"state": "interrupted"})

                # If segment accumulation or commit timer is active, let _commit_full_turn handle the full turn!
                # Only directly dispatch if no accumulation callback was hooked (fallback for raw tests)
                if not self._accumulated_speech_segments and not (self._commit_timer_task and not self._commit_timer_task.done()):
                    if self._active_turn_task and not self._active_turn_task.done():
                        self._active_turn_task.cancel()
                    self._active_turn_task = asyncio.create_task(self.handle_candidate_answer(speech_text))

        elif isinstance(frame, (BotStartedSpeakingFrame, TTSStartedFrame)):
            self.is_speaking = True
            if self._stt_service is not None:
                self._stt_service.set_bot_speaking(True)
                self._stt_service.last_ai_speech = self.last_ai_speech
            self.is_thinking = False
            self._awaiting_first_bot_audio = False
            self._last_activity_monotonic = time.monotonic()
            await self.emit_ui_state("interview-bot-state", {"state": "speaking"})

        elif isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame)):
            self.is_speaking = False
            if self._stt_service is not None:
                self._stt_service.set_bot_speaking(False)
            self._last_activity_monotonic = time.monotonic()
            await self.emit_ui_state("interview-bot-state", {"state": "listening"})

        elif isinstance(frame, InterruptionFrame):
            # Guard against raw VAD transient interruptions while speaking;
            # substantive interruptions are handled by TranscriptionFrame with the 350ms duration guard and backchannel filter.
            if not self.is_speaking:
                await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)


class LiveInterviewRunner:
    """Manages the Pipecat pipeline runner, connection, and coordinator for a session."""

    def __init__(
        self,
        session_id: str,
        candidate_name: str,
        role_title: str,
        questions: List[Dict[str, Any]],
        candidate_local_hour: Optional[int] = None,
        max_followup_depth: int = 1,
        duration_planned_mins: float = 20.0,
        allow_grace_extension: bool = True,
        pacing_strictness: str = "Balanced",
        skill_time_allocations_mins: Optional[Dict[str, float]] = None,
        interviewer_brief: str = "",
        job_public_fields: Optional[Dict[str, Any]] = None,
        application_id: Optional[str] = None,
        integrity_policy_tier: str = "Moderate",
        speech_speed: float = 1.0,
        captions_enabled: bool = True,
    ):
        self.session_id = session_id
        self.application_id = application_id
        self.candidate_name = candidate_name
        self.role_title = role_title
        self.questions = questions
        self.candidate_local_hour = candidate_local_hour
        self.max_followup_depth = max_followup_depth
        self.duration_planned_mins = duration_planned_mins
        self.allow_grace_extension = allow_grace_extension
        self.pacing_strictness = pacing_strictness
        self.skill_time_allocations_mins = skill_time_allocations_mins or {}
        self.interviewer_brief = interviewer_brief
        self.job_public_fields = job_public_fields or {"job_title": role_title}
        self.integrity_policy_tier = integrity_policy_tier
        self.speech_speed = speech_speed
        self.captions_enabled = captions_enabled

        self.handler = SmallWebRTCRequestHandler()
        self.connection: Optional[SmallWebRTCConnection] = None
        self.coordinator: Optional[InterviewCoordinatorProcessor] = None
        self.tts_service = None
        self.stt_service = None
        self.task: Optional[PipelineTask] = None
        self.runner: Optional[PipelineRunner] = None
        self._runner_task: Optional[asyncio.Task] = None

    async def prewarm_greeting(self) -> None:
        """Pre-render the personalized greeting + ready-check during pre-flight so 'Begin' starts instantly (Part A4)."""
        temp_coord = InterviewCoordinatorProcessor(
            session_id=self.session_id,
            candidate_name=self.candidate_name,
            role_title=self.role_title,
            questions=self.questions,
            candidate_local_hour=self.candidate_local_hour,
            enable_silence_monitor=False,
        )
        greeting_text, ready_text = temp_coord._build_greeting_and_ready_check()
        combined = f"{greeting_text} {ready_text}"
        intro_prompt = (
            f"Great! To get started, please tell me a bit about yourself and your relevant background in {self.role_title}."
        )
        await pre_synthesize_phrase(combined, speed=self.speech_speed)
        await pre_synthesize_phrase(intro_prompt, speed=self.speech_speed)

        # Pre-warm Gemini live client connection during pre-flight
        try:
            from backend.app.services.question_generation.provider import warm_gemini_client
            asyncio.to_thread(warm_gemini_client)
        except Exception:
            pass

    async def on_connection(self, connection: SmallWebRTCConnection):
        """Callback invoked when SmallWebRTC creates a peer connection."""
        self.connection = connection

        self.coordinator = InterviewCoordinatorProcessor(
            session_id=self.session_id,
            application_id=self.application_id,
            candidate_name=self.candidate_name,
            role_title=self.role_title,
            questions=self.questions,
            candidate_local_hour=self.candidate_local_hour,
            max_followup_depth=self.max_followup_depth,
            duration_planned_mins=self.duration_planned_mins,
            allow_grace_extension=self.allow_grace_extension,
            pacing_strictness=self.pacing_strictness,
            skill_time_allocations_mins=self.skill_time_allocations_mins,
            interviewer_brief=self.interviewer_brief,
            job_public_fields=self.job_public_fields,
            integrity_policy_tier=self.integrity_policy_tier,
            speech_speed=self.speech_speed,
            captions_enabled=self.captions_enabled,
        )

        comps = build_voice_pipeline_components(
            connection,
            speech_speed=self.speech_speed,
            on_stt_interim=self.coordinator.record_stt_interim,
            on_stt_final=self.coordinator.record_stt_metrics,
            on_tts_first_audio=self.coordinator.record_tts_first_audio,
            session_trace=self.coordinator.session_trace,
        )
        self.tts_service = comps["tts"]
        self.stt_service = comps["stt"]
        self.coordinator._stt_service = self.stt_service
        self.coordinator._audio_segments_received_fn = lambda: getattr(self.stt_service, "audio_segments_received", 1)
        comps["lag_monitor"].start()
        self.lag_monitor = comps["lag_monitor"]

        # Pre-warm greeting audio in background during connection handshake
        asyncio.create_task(self.prewarm_greeting())

        pipeline_processors = [
            comps["transport"].input(),
            comps["rtvi"],
            comps["vad"],
            comps["turn_analyzer"],
            comps["stt"],
            self.coordinator,
            comps["tts"],
        ]
        if comps["avatar"] is not None:
            pipeline_processors.append(comps["avatar"])
        pipeline_processors.append(comps["transport"].output())

        pipeline = Pipeline(pipeline_processors)

        self.task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=24000,
            ),
            observers=[comps["rtvi_observer"]],
        )

        self.runner = PipelineRunner()
        self._runner_task = asyncio.create_task(self.runner.run(self.task))

        @connection.event_handler("closed")
        async def _on_close(conn):
            await self.handle_disconnect()

    async def handle_disconnect(self):
        """If session was in_progress and not completed, transition to 'paused' so candidate can reconnect (Part C1)."""
        if self.coordinator and self.coordinator.has_begun and not self.coordinator.is_completed:
            try:
                async with AsyncSessionLocal() as db:
                    s_row = (
                        await db.execute(select(InterviewSession).where(InterviewSession.id == self.session_id))
                    ).scalars().first()
                    if s_row and s_row.status == "in_progress":
                        s_row.status = "paused"
                        s_row.paused_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        s_row.current_phase = self.coordinator.current_phase.value
                        s_row.current_question_index = self.coordinator.current_question_index
                        s_row.running_summary = self.coordinator.running_summary
                        await db.commit()
                        logger.info(f"Session {self.session_id} paused on disconnect; awaiting reconnect.")
            except Exception as exc:
                logger.debug(f"Pause on disconnect notice: {exc}")
        await interview_manager.cleanup_session(self.session_id)

    async def cleanup(self):
        try:
            if hasattr(self, "lag_monitor") and self.lag_monitor:
                try:
                    self.lag_monitor.stop()
                except Exception:
                    pass
            if self.coordinator and self.coordinator._silence_task and not self.coordinator._silence_task.done():
                self.coordinator._silence_task.cancel()
            if self.runner:
                try:
                    await self.runner.cancel()
                except Exception as ce:
                    logger.debug(f"Runner cancel notice: {ce}")
            if self.task:
                try:
                    await self.task.cancel()
                except Exception as te:
                    logger.debug(f"Task cancel notice: {te}")
            if self._runner_task and not self._runner_task.done():
                self._runner_task.cancel()
                try:
                    await self._runner_task
                except (asyncio.CancelledError, Exception):
                    pass
        except Exception as e:
            logger.debug(f"Live interview cleanup notice: {e}")


class LiveInterviewManager:
    """Singleton registry of active live interview rooms with single-session MLX concurrency guard (Part C4)."""

    _instance = None

    def __init__(self):
        self._runners: Dict[str, LiveInterviewRunner] = {}
        self._probe_handler = SmallWebRTCRequestHandler()
        self.max_concurrent_sessions: int = int(os.getenv("MAX_CONCURRENT_INTERVIEWS", "1"))

    @classmethod
    def get_instance(cls) -> "LiveInterviewManager":
        if cls._instance is None:
            cls._instance = LiveInterviewManager()
        return cls._instance

    def is_busy_for_session(self, session_id: str) -> bool:
        """Return True if another live session is currently active on this local MLX worker."""
        active_other = [
            sid
            for sid, r in self._runners.items()
            if sid != session_id
            and r.coordinator is not None
            and not r.coordinator.is_completed
        ]
        return len(active_other) >= self.max_concurrent_sessions

    def get_or_create_runner(
        self,
        session_id: str,
        candidate_name: str,
        role_title: str,
        questions: List[Dict[str, Any]],
        candidate_local_hour: Optional[int] = None,
        max_followup_depth: int = 1,
        duration_planned_mins: float = 20.0,
        allow_grace_extension: bool = True,
        pacing_strictness: str = "Balanced",
        skill_time_allocations_mins: Optional[Dict[str, float]] = None,
        interviewer_brief: str = "",
        job_public_fields: Optional[Dict[str, Any]] = None,
        application_id: Optional[str] = None,
        integrity_policy_tier: str = "Moderate",
        speech_speed: float = 1.0,
        captions_enabled: bool = True,
    ) -> LiveInterviewRunner:
        if self.is_busy_for_session(session_id):
            raise InterviewerBusyError(
                "Another live voice interview is currently in progress on this server. Please wait a moment and retry."
            )
        if session_id not in self._runners:
            runner = LiveInterviewRunner(
                session_id=session_id,
                application_id=application_id,
                candidate_name=candidate_name,
                role_title=role_title,
                questions=questions,
                candidate_local_hour=candidate_local_hour,
                max_followup_depth=max_followup_depth,
                duration_planned_mins=duration_planned_mins,
                allow_grace_extension=allow_grace_extension,
                pacing_strictness=pacing_strictness,
                skill_time_allocations_mins=skill_time_allocations_mins,
                interviewer_brief=interviewer_brief,
                job_public_fields=job_public_fields,
                integrity_policy_tier=integrity_policy_tier,
                speech_speed=speech_speed,
                captions_enabled=captions_enabled,
            )
            self._runners[session_id] = runner
        return self._runners[session_id]

    async def handle_offer(
        self,
        session_id: str,
        request_dict: Dict[str, Any],
        candidate_name: str,
        role_title: str,
        questions: List[Dict[str, Any]],
        candidate_local_hour: Optional[int] = None,
        max_followup_depth: int = 1,
        duration_planned_mins: float = 20.0,
        allow_grace_extension: bool = True,
        pacing_strictness: str = "Balanced",
        skill_time_allocations_mins: Optional[Dict[str, float]] = None,
        interviewer_brief: str = "",
        job_public_fields: Optional[Dict[str, Any]] = None,
        application_id: Optional[str] = None,
        integrity_policy_tier: str = "Moderate",
        speech_speed: float = 1.0,
        captions_enabled: bool = True,
    ) -> Dict[str, Any]:
        runner = self.get_or_create_runner(
            session_id=session_id,
            application_id=application_id,
            candidate_name=candidate_name,
            role_title=role_title,
            questions=questions,
            candidate_local_hour=candidate_local_hour,
            max_followup_depth=max_followup_depth,
            duration_planned_mins=duration_planned_mins,
            allow_grace_extension=allow_grace_extension,
            pacing_strictness=pacing_strictness,
            skill_time_allocations_mins=skill_time_allocations_mins,
            interviewer_brief=interviewer_brief,
            job_public_fields=job_public_fields,
            integrity_policy_tier=integrity_policy_tier,
            speech_speed=speech_speed,
            captions_enabled=captions_enabled,
        )
        req = SmallWebRTCRequest.from_dict(request_dict)
        answer = await runner.handler.handle_web_request(req, runner.on_connection)
        return answer

    async def handle_patch(self, session_id: str, patch_dict: Dict[str, Any]):
        runner = self._runners.get(session_id)
        if not runner:
            raise KeyError(f"No active live session found for {session_id}")
        candidates = [IceCandidate(**c) for c in patch_dict.get("candidates", [])]
        req = SmallWebRTCPatchRequest(pc_id=patch_dict["pc_id"], candidates=candidates)
        await runner.handler.handle_patch_request(req)

    async def begin_session(self, session_id: str):
        runner = self._runners.get(session_id)
        if not runner or not runner.coordinator:
            logger.warning(f"No active runner found for session {session_id} in {list(self._runners.keys())}")
            raise KeyError(f"No active live session runner found for {session_id}")
        logger.info(f"=== [LiveInterviewManager] Launching interview greeting for session {session_id} ===")
        await runner.coordinator.begin_interview()

    async def repeat_question(self, session_id: str) -> str:
        runner = self._runners.get(session_id)
        if not runner or not runner.coordinator:
            raise KeyError(f"No active live session runner found for {session_id}")
        return await runner.coordinator.repeat_current_question()

    async def update_session_settings(
        self,
        session_id: str,
        speech_speed: Optional[float] = None,
        captions_enabled: Optional[bool] = None,
    ) -> None:
        runner = self._runners.get(session_id)
        if not runner:
            return
        if speech_speed is not None:
            runner.speech_speed = speech_speed
            if runner.tts_service:
                runner.tts_service.set_speed(speech_speed)
            if runner.coordinator:
                runner.coordinator.speech_speed = speech_speed
        if captions_enabled is not None and runner.coordinator:
            runner.coordinator.captions_enabled = captions_enabled

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        runner = self._runners.get(session_id)
        if not runner or not runner.coordinator:
            return {
                "active": False,
                "phase": "scheduled",
                "interviewer_busy": self.is_busy_for_session(session_id),
            }
        c = runner.coordinator
        return {
            "active": True,
            "has_begun": c.has_begun,
            "phase": c.current_phase.value,
            "is_speaking": c.is_speaking,
            "is_thinking": c.is_thinking,
            "current_question_index": c.current_question_index,
            "total_questions": len(c.questions),
            "is_completed": c.is_completed,
            "last_ai_speech": c.last_ai_speech,
            "last_candidate_speech": c.last_candidate_speech,
            "remaining_seconds": round(c.pacing.remaining_seconds(), 1),
            "grace_extended": c.pacing.grace_extended,
            "speech_speed": c.speech_speed,
            "captions_enabled": c.captions_enabled,
        }

    async def handle_probe_offer(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Ephemeral probe for pre-flight network checks."""
        req = SmallWebRTCRequest.from_dict(request_dict)

        async def _probe_cb(connection: SmallWebRTCConnection):
            logger.info("WebRTC probe peer connection initialized.")

        return await self._probe_handler.handle_web_request(req, _probe_cb)

    async def handle_probe_patch(self, patch_dict: Dict[str, Any]):
        candidates = [IceCandidate(**c) for c in patch_dict.get("candidates", [])]
        req = SmallWebRTCPatchRequest(pc_id=patch_dict["pc_id"], candidates=candidates)
        await self._probe_handler.handle_patch_request(req)

    async def cleanup_session(self, session_id: str):
        runner = self._runners.pop(session_id, None)
        if runner:
            await runner.cleanup()

    async def cleanup_all(self):
        runners = list(self._runners.values())
        self._runners.clear()
        for runner in runners:
            await runner.cleanup()


interview_manager = LiveInterviewManager.get_instance()
