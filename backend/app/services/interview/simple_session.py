"""R3.5 simple interview mode: a deterministic, scripted interviewer.

Configured by INTERVIEW_MODE=simple (the default). Zero LLM calls in the live
loop — the entire interview is a rule-driven state machine over the materialized
question plan:

    welcome (one utterance: greeting, AI disclosure, duration, monitoring notice,
    agenda) -> ready gate ("Ready to begin?" waits for yes/ready/ok) -> intro hook
    -> per-skill [anchor (+ anchor_alt on "no experience") -> escalation]
    -> candidate Q&A -> closing

Strict single-question turn state machine:

    ASKING  (bot is speaking a scripted question)
    LISTENING (candidate answering; live words stream to the UI)
    COMMITTED (answer captured; bridge + next question spoken)

Turn commit triggers (first one wins):
  - POST /api/interview-sessions/{id}/commit-turn  (the "I'm done answering" button)
  - "that's my answer" / "I'm done answering" spoken phrase
  - AUTO_COMMIT_SILENCE (default 2.5 s) after the candidate stops speaking

No bot speech ever overlaps candidate speech: barge-in is disabled by default
(ALLOW_BARGE_IN=false) and the UI shows an "AI is speaking, please wait" pill.

All rule-based speech is tiny and scripted:
  - bridges <= 3 words ("Got it.", "Thanks.")
  - skill transitions <= 12 words ("Now let's move to <topic>. <anchor>")
  - escalation questions verbatim from the blueprint
  - short answers (< 4 words) get "Could you say a bit more?" exactly once
"""

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame

from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.models import InterviewSession, InterviewTranscriptTurn
from backend.app.services.interview.trace import SessionTrace
from backend.app.services.interview.state_machine import InterviewPhase, PacingController, TurnType
from backend.app.services.interview.stt_provider import stitch_sliding_text
from backend.app.services.interview.voice_pipeline import is_acoustic_echo
from backend.app.services.interview.turn_evaluator import evaluate_interview_session

AUTO_COMMIT_SILENCE_SECS = float(os.getenv("AUTO_COMMIT_SILENCE", "2.5"))
ALLOW_BARGE_IN = os.getenv("ALLOW_BARGE_IN", "false").strip().lower() == "true"
QUESTIONS_PER_SKILL = int(os.getenv("QUESTIONS_PER_SKILL", "2"))
RESUME_PROBES = os.getenv("RESUME_PROBES", "false").strip().lower() == "true"
SILENCE_NUDGE_SECS = float(os.getenv("SIMPLE_SILENCE_NUDGE_SECS", "22.0"))

# Phrases that explicitly hand the turn back to the interviewer.
_COMMIT_PHRASES = (
    "that's my answer",
    "thats my answer",
    "that is my answer",
    "i'm done answering",
    "im done answering",
    "i am done answering",
    "thats all i have",
    "i am done",
    "im done",
)

_NO_EXPERIENCE_RE = re.compile(
    r"\b(no ?experience|never (?:worked|used|built|done)|haven'?t (?:worked|used|done)|"
    r"don'?t (?:know|have|use)|not familiar|i haven'?t)\b",
    re.IGNORECASE,
)
_SHORT_ANSWER_WORDS = 4
_BRIDGES = ("Got it.", "Thanks.", "Okay.", "Alright.")
_SHORT_PROMPT = "Could you say a bit more?"
_TRANSITION_FILLERS = ("Alright", "Okay", "Great", "Got it")

# Welcome ready-gate (R3.5b): after the welcome utterance, the bot waits for an
# acknowledgment before speaking the intro question as a separate utterance.
_READY_ACK_RE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|okay|ready|let'?s go|lets go|let'?s begin|lets begin|"
    r"let'?s start|lets start|go ahead|sounds good|alright|affirmative|please do|begin|start)\b",
    re.IGNORECASE,
)
_WELCOME_GATE_SILENCE_SECS = float(os.getenv("WELCOME_GATE_SILENCE_SECS", "8.0"))

_REPEAT_RE = re.compile(
    r"\b(repeat|clarify|come again|didn'?t (?:hear|catch|understand)|one more time|say (?:that )?again|"
    r"what (?:are you|did you) (?:say|ask|asking)|what is the question|can you (?:say|repeat)|could you (?:say|repeat)|pardon)\b",
    re.IGNORECASE,
)

_EMPTY_ANSWER_SEQUENCE_SENTINEL = "__empty__"


def clean_role_title_for_speech(role: Optional[str]) -> str:
    """Normalize role titles for spoken TTS so hyphens/dashes are never spoken as 'minus' (e.g. 'SDE -1' -> 'Software Development Engineer 1')."""
    if not role:
        return "Software Engineer"
    cleaned = str(role)
    cleaned = re.sub(r"\s*[\-–—_]+\s*", " ", cleaned).strip()
    cleaned = re.sub(r"\bSDE\s*I\b", "Software Development Engineer 1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*II\b", "Software Development Engineer 2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*III\b", "Software Development Engineer 3", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*1\b", "Software Development Engineer 1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*2\b", "Software Development Engineer 2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*3\b", "Software Development Engineer 3", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\b", "Software Development Engineer", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSWE\b", "Software Engineer", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _normalize_for_phrase_match(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", t)


def _strip_commit_phrases(text: str) -> tuple[str, bool]:
    """Return (remaining_text, phrase_was_spoken). Detects commit phrases anywhere."""
    cleaned = (text or "").strip()
    lowered_norm = _normalize_for_phrase_match(cleaned)
    for phrase in _COMMIT_PHRASES:
        if phrase in lowered_norm:
            return cleaned, True
    return cleaned, False


def _remove_commit_phrase(text: str) -> str:
    out = (text or "").strip()
    lowered_norm = _normalize_for_phrase_match(out)
    for phrase in _COMMIT_PHRASES:
        if phrase in lowered_norm:
            idx = lowered_norm.find(phrase)
            tail = out[idx + len(phrase):]
            return (out[:idx] + " " + tail).strip(" ,.-")
    return out


def _word_count(text: str) -> int:
    return len([w for w in re.findall(r"[A-Za-z0-9']+", (text or ""))])


class SimpleInterviewCoordinator(FrameProcessor):
    """Scripted interviewer for INTERVIEW_MODE=simple. No LLM in the live loop."""

    # Explicit simple-mode turn states (kept simple on purpose).
    ST_ASKING = "asking"
    ST_LISTENING = "listening"
    ST_COMMITTED = "committed"

    def __init__(
        self,
        session_id: str,
        candidate_name: str = "Candidate",
        role_title: str = "Software Engineer",
        questions: Optional[List[Dict[str, Any]]] = None,
        candidate_local_hour: Optional[int] = None,
        duration_planned_mins: float = 20.0,
        allow_grace_extension: bool = True,
        skill_time_allocations_mins: Optional[Dict[str, float]] = None,
        job_public_fields: Optional[Dict[str, Any]] = None,
        speech_speed: float = 1.0,
        captions_enabled: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.session_id = session_id
        self.candidate_name = candidate_name or "Candidate"
        self.role_title = role_title or "Software Engineer"
        self.questions = questions or []
        self.candidate_local_hour = candidate_local_hour
        self.speech_speed = speech_speed
        self.captions_enabled = captions_enabled

        self.pacing = PacingController(
            duration_planned_mins=duration_planned_mins,
            allow_grace_extension=allow_grace_extension,
            skill_time_allocations_mins=skill_time_allocations_mins or {},
        )

        # --- scripted plan ---------------------------------------------------
        self.welcome_q: Optional[Dict[str, Any]] = None
        self.intro_q: Optional[Dict[str, Any]] = None
        self.candidate_qa_q: Optional[Dict[str, Any]] = None
        self.closing_q: Optional[Dict[str, Any]] = None
        self.skill_groups: List[Dict[str, Any]] = []  # {name, spoken_label, anchor, anchor_alt, escalation}
        self.steps: List[Dict[str, Any]] = []         # {"kind", "q", "skill_idx"}
        self._step = -1                               # -1 = pre-greeting
        self._build_scripted_plan()

        # --- state machine ----------------------------------------------------
        self.state: str = self.ST_LISTENING
        self.current_phase = InterviewPhase.GREETING
        self.has_begun = False
        self.is_completed = False
        self.is_speaking = False
        self.current_lead_question_index = 0  # leading question index for progress payloads
        self.lock = asyncio.Lock()
        self._speak_lock = asyncio.Lock()
        self._commit_lock = asyncio.Lock()
        self._is_committing: bool = False

        # --- question ledger / reply state ------------------------------------
        self.asked_ledger: List[Dict[str, Any]] = []
        self.skill_state: Dict[int, Dict[str, Any]] = {}
        self._short_prompt_active = False      # the "Could you say a bit more?" prompt turn
        self._short_prompt_target_step: Optional[int] = None
        self._empty_prompt_count = 0

        # --- welcome ready-gate (R3.5b) ---------------------------------------
        self._awaiting_ready = False
        self._welcome_gate_reprompted = False

        # --- answer accumulation ----------------------------------------------
        self._turn_text: str = ""
        self._turn_chunks: List[str] = []
        self._speech_started_monotonic: Optional[float] = None
        self._speech_active: bool = False
        self._commit_reason: Optional[str] = None
        self._last_commit_monotonic: float = 0.0
        self._commits_total = 0

        # --- timers ------------------------------------------------------------
        self._auto_commit_task: Optional[asyncio.Task] = None
        self._silence_task: Optional[asyncio.Task] = None
        self._silence_nudges = 0
        self._last_activity_monotonic = time.monotonic()

        self.last_ai_speech = ""
        self.last_candidate_speech = ""
        self.running_summary = ""

        # STT service wiring (set by the runner)
        self._stt_service: Optional[Any] = None
        self._stt_wait_task: Optional[asyncio.Task] = None

        self.session_trace = SessionTrace(self.session_id)

    # ------------------------------------------------------------------ plan

    def _build_scripted_plan(self) -> None:
        """Turn the question list into a fixed ordered script of steps."""
        by_kind = lambda kind: [q for q in self.questions if (q.get("kind") == kind)]

        welcomes = by_kind("welcome")
        self.welcome_q = welcomes[0] if welcomes else None
        intros = by_kind("intro_hook")
        self.intro_q = intros[0] if intros else None
        qa = by_kind("candidate_qa")
        self.candidate_qa_q = qa[0] if qa else None
        closings = by_kind("closing")
        self.closing_q = closings[0] if closings else None

        # Guard: sanitize intro_hook and any fragment questions into full, scenario-grounded questions
        if self.intro_q:
            itxt = (self.intro_q.get("question_text") or "").strip()
            if not itxt or not itxt.endswith("?") or itxt.lower().startswith("your work") or itxt.lower().startswith("the project") or not any(itxt.lower().startswith(w) for w in ["to ", "could you", "can you", "please", "walk me", "tell me"]):
                self.intro_q["question_text"] = "To start off, could you please introduce yourself, tell me about your background, and share some highlights from your key projects and experiences?"

        for q in self.questions:
            t = (q.get("question_text") or "").strip()
            if t and (not t.endswith("?") or t.lower().startswith("your work") or t.lower().startswith("the project") or t.lower().startswith("designing") or t.lower().startswith("reducing")):
                if t.lower().startswith("your work") or t.lower().startswith("the project") or t.lower().startswith("designing") or t.lower().startswith("reducing"):
                    q["question_text"] = f"Could you walk me through {t[0].lower() + t[1:].rstrip('?.')}?"
                elif not t.endswith("?"):
                    q["question_text"] = t + "?"

        ordered = sorted(self.questions, key=lambda q: q.get("question_index", 0))
        group_map: Dict[str, Dict[str, Any]] = {}
        skill_names: List[str] = []
        admin_kinds = {"welcome", "intro_hook", "candidate_qa", "closing", "resume_probe"}
        for q in ordered:
            kind = q.get("kind") or ""
            sname = q.get("skill_name") or ""
            if kind in admin_kinds or not sname:
                continue
            g = group_map.get(sname)
            if g is None:
                g = {"name": sname, "label": sname, "anchor": None, "anchor_alt": None, "escalation": None, "probes": []}
                group_map[sname] = g
                skill_names.append(sname)
            if kind == "anchor" and g["anchor"] is None:
                g["anchor"] = q
            elif kind == "anchor_alt" and g["anchor_alt"] is None:
                g["anchor_alt"] = q
            elif kind == "escalation" and g["escalation"] is None:
                g["escalation"] = q
            elif kind in ("probe", "resume_probe") and not RESUME_PROBES and kind == "resume_probe":
                continue
            else:
                g["probes"].append(q)

        self.skill_groups = [group_map[n] for n in skill_names]

        # Ordered steps: welcome -> intro -> per-skill -> candidate_qa -> closing.
        if self.welcome_q:
            self.steps.append({"kind": "welcome", "q": self.welcome_q, "skill_idx": -1})
        if self.intro_q:
            self.steps.append({"kind": "intro", "q": self.intro_q, "skill_idx": -1})
        for gi, g in enumerate(self.skill_groups):
            first = g["anchor"] or (g["probes"][0] if g["probes"] else None) or g["anchor_alt"]
            if first:
                self.steps.append({"kind": "anchor", "q": first, "skill_idx": gi})
            if g["escalation"]:
                self.steps.append({"kind": "escalation", "q": g["escalation"], "skill_idx": gi})
        if self.candidate_qa_q:
            self.steps.append({"kind": "candidate_qa", "q": self.candidate_qa_q, "skill_idx": -1})
        if self.closing_q:
            self.steps.append({"kind": "closing", "q": self.closing_q, "skill_idx": -1})

    # ------------------------------------------------------------- helpers

    def _spoken_skill_label(self, gi: int) -> str:
        if 0 <= gi < len(self.skill_groups):
            return self.skill_groups[gi].get("label") or self.skill_groups[gi]["name"]
        return "the next topic"

    def _persist_progress_payload(self) -> Dict[str, Any]:
        # topic_index is 1-BASED for skill sections (Topic 1 = first skill); 0 while
        # the flow is still in welcome/intro (no topic yet).
        cur = self.steps[self._step] if 0 <= self._step < len(self.steps) else None
        gi = (cur or {}).get("skill_idx", -1)
        topic_idx = (gi + 1) if gi >= 0 else 0
        return {
            "step": self._step,
            "question_index": (cur or {}).get("q", {}).get("question_index", self.current_lead_question_index),
            "text": (cur or {}).get("q", {}).get("question_text", ""),
            "skill_name": (cur or {}).get("q", {}).get("skill_name", ""),
            "kind": (cur or {}).get("kind", ""),
            "topic_index": topic_idx,
            "topic_total": len(self.skill_groups),
            "mode": "simple",
        }

    async def _emit(self, message_type: str, payload: Dict[str, Any]) -> None:
        data = {
            "type": message_type,
            "session_id": self.session_id,
            "phase": self.current_phase.value,
            "mode": "simple",
            "remaining_seconds": round(self.pacing.remaining_seconds(), 1),
            "captions_enabled": self.captions_enabled,
            "speech_speed": self.speech_speed,
            "state": self.state,
            "timestamp": time.time(),
            **payload,
        }
        try:
            await self.push_frame(RTVIServerMessageFrame(data=data), FrameDirection.DOWNSTREAM)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[simple] emit {message_type} notice: {exc}")

    def _next_sequence(self) -> int:
        env_val = os.getenv(f"SIMPLE_SEQ_{self.session_id}")
        seq = int(env_val or "0") + 1
        os.environ[f"SIMPLE_SEQ_{self.session_id}"] = str(seq)
        return seq

    async def persist_turn(
        self,
        turn_type: str,
        speaker: str,
        text: str,
        question_id: Optional[str] = None,
        stt_final_ms: Optional[float] = None,
        provider: Optional[str] = None,
        commit_reason: Optional[str] = None,
        speech_duration_ms: Optional[float] = None,
    ) -> Optional[InterviewTranscriptTurn]:
        """Persist a transcript turn (with provider + R3.5 timings) to the DB."""
        clean_text = (text or "").strip()
        if not clean_text:
            return None
        details = {
            "commit_reason": commit_reason,
            "speech_duration_ms": speech_duration_ms,
            "interview_mode": "simple",
        }
        try:
            # details_json is added only when the model maps that column (some DB
            # snapshots omit it): passing an unmapped kwarg makes the ORM reject
            # the constructor and the turn is silently lost (logger.debug only).
            turn_kwargs = dict(
                session_id=self.session_id,
                question_id=question_id,
                turn_type=turn_type,
                speaker=speaker,
                text=clean_text,
                spoken_text=clean_text if speaker == "ai" else None,
                stt_final_ms=stt_final_ms,
                provider=provider,
                model_name=f"stt:{provider}" if provider and speaker == "candidate" else None,
                sequence_number=self._next_sequence(),
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            if hasattr(InterviewTranscriptTurn, "details_json"):
                turn_kwargs["details_json"] = details
            turn = InterviewTranscriptTurn(**turn_kwargs)
            async with AsyncSessionLocal() as db:
                db.add(turn)
                await db.commit()
                await db.refresh(turn)
            if speaker == "ai":
                self.last_ai_speech = clean_text
                if self._stt_service is not None:
                    self._stt_service.last_ai_speech = clean_text
            else:
                self.last_candidate_speech = clean_text
            return turn
        except Exception as exc:
            logger.debug(f"[simple] persist_turn({turn_type}) notice: {exc}")
            return None

    def _build_greeting_text(self) -> str:
        first_name = self.candidate_name.split()[0] if self.candidate_name else "Candidate"
        clean_role = clean_role_title_for_speech(self.role_title)
        labels = [g.get("label") or g["name"] for g in self.skill_groups]
        if labels:
            agenda = ", ".join(labels[:-1]) + (f", and {labels[-1]}" if len(labels) > 1 else labels[0])
        else:
            agenda = "your background and experience"
        duration_mins = int(self.pacing.duration_planned_mins)
        # R3.5b one-utterance welcome: AI disclosure, duration, monitoring notice,
        # agenda — ending in the "Ready to begin?" gate question.
        return (
            f"Hi {first_name}, I'm your AI interviewer for the {clean_role} role. "
            f"You're speaking with an AI, not a human, and this session is recorded and monitored for interview integrity. "
            f"Our conversation will take about {duration_mins} minutes. "
            f"We'll cover {agenda}, and I'll leave time at the end for your questions. "
            f"One question at a time, and answer in your own style. "
            f"If you'd like me to repeat anything, just ask. Ready to begin?"
        )

    # ---------------------------------------------------------------- TTS

    async def speak(
        self,
        text: str,
        turn_type: str,
        question_id: Optional[str] = None,
        phase: Optional[InterviewPhase] = None,
    ) -> None:
        """Speech lock: one scripted utterance at a time, never over a candidate."""
        text = (text or "").strip()
        if not text:
            return
        async with self._speak_lock:
            self.state = self.ST_ASKING
            self.current_phase = phase or self.current_phase
            await self.persist_turn(
                turn_type=turn_type,
                speaker="ai",
                text=text,
                question_id=question_id,
            )
            await self._emit("ai-speech-transcript", {"text": text, "question_id": question_id})
            await self._emit(
                "interview-progress",
                {**self._persist_progress_payload(), "question_id": question_id},
            )
            await self._emit("interview-bot-state", {"state": "speaking"})
            await self.push_frame(TTSSpeakFrame(text), FrameDirection.DOWNSTREAM)
            self._last_activity_monotonic = time.monotonic()
            # Pre-warm the likely NEXT utterances (bridge/next question) while the
            # candidate is answering, so a commit plays instantly (cache hit).
            self._kick_prewarm()

    async def _prewarm_next_speech(self) -> None:
        """Pre-warm the TTS cache for bridge + likely next steps while the user talks.

        Runs in a worker thread (idle listening time), so the commit -> audible
        bridge/next question is instant (warm cache path ~150-500ms -> ~0ms first audio).
        """
        next_texts: List[str] = []
        for b in _BRIDGES:
            next_texts.append(b)
        nxt = self._step + 1
        if 0 <= nxt < len(self.steps):
            nq = self.steps[nxt]["q"]
            ntext = (nq.get("question_text") or "").strip()
            if ntext:
                gi = self.steps[nxt].get("skill_idx", -1)
                if self.steps[nxt]["kind"] in ("anchor", "anchor_alt") and gi >= 0:
                    prev = self.steps[self._step] if 0 <= self._step < len(self.steps) else None
                    if prev and prev["skill_idx"] != gi:
                        ntext = f"Alright. Now let's talk about {self._spoken_skill_label(gi)}. {ntext}"
                next_texts.append(ntext)
        next_texts.append(_SHORT_PROMPT)
        try:
            for t in next_texts:
                from backend.app.services.interview.voice_pipeline import pre_synthesize_phrase

                await pre_synthesize_phrase(t, speed=self.speech_speed)
        except Exception as exc:
            logger.debug(f"[simple] TTS pre-warm notice: {exc}")

    def _kick_prewarm(self) -> None:
        task = getattr(self, "_prewarm_task", None)
        if task is None or task.done():
            self._prewarm_task = asyncio.create_task(self._prewarm_next_speech())

    async def _ask_step(self, step_idx: int) -> None:
        self._is_committing = False
        self._turn_text = ""
        self._turn_chunks = []
        if self._stt_service is not None and hasattr(self._stt_service, "reset_turn"):
            self._stt_service.reset_turn()
        asyncio.create_task(self._emit("candidate-speech-transcript", {"text": "", "is_final": True}))
        self._step = step_idx
        if self._step >= len(self.steps):
            await self._finish_flow()
            return
        step = self.steps[self._step]
        q = step["q"]
        gi = step["skill_idx"]
        if gi >= 0 and gi not in self.skill_state:
            self.skill_state[gi] = {"used_anchor_alt": False, "short_prompt_used": False, "answered": 0, "kinds": []}
        ledg = {"step_kind": step["kind"], "question_id": q.get("id"), "at": time.time(), "seq": self._next_sequence()}
        self.asked_ledger.append(ledg)

        if step["kind"] in ("anchor", "anchor_alt"):
            phase = InterviewPhase.DEEP_DIVE
            text = (q.get("question_text") or "").strip()
        elif step["kind"] == "intro":
            phase = InterviewPhase.SELF_INTRO
            text = (q.get("question_text") or "").strip()
        elif step["kind"] == "candidate_qa":
            phase = InterviewPhase.CANDIDATE_QUESTIONS
            text = (q.get("question_text") or "").strip()
        elif step["kind"] == "closing":
            phase = InterviewPhase.CLOSING
            text = (q.get("question_text") or "").strip()
        else:
            phase = InterviewPhase.DEEP_DIVE
            text = (q.get("question_text") or "").strip()

        # Intro step includes the welcome agenda before the first question (no dead air);
        # when welcome+intro are merged in begin_interview, self._step points at intro.
        if step["kind"] == "welcome":
            phase = InterviewPhase.GREETING
            # R3.5b: the greeting text itself carries disclosure + duration + monitoring
            # notice + agenda + "Ready to begin?" — arm the ready gate behind it.
            text = self._build_greeting_text()
            self._awaiting_ready = True
            self._welcome_gate_reprompted = False
            self._welcome_gate_started = time.monotonic()

        if gi >= 0 and step["kind"] in ("anchor", "anchor_alt") and self._step >= 0:
            prev = self.steps[self._step - 1] if self._step > 0 else None
            if prev and prev["skill_idx"] != gi and self.skill_groups:
                # Skill transition: <= 12 words.
                answered = self.skill_state.get(gi, {}).get("answered", 0)
                filler = _TRANSITION_FILLERS[min(len(_TRANSITION_FILLERS) - 1, max(0, answered))]
                transition = f"{filler}. Now let's talk about {self._spoken_skill_label(gi)}."
                logger.info(f"[simple] skill transition ({len(transition.split())} words): {transition!r}")
                text = f"{transition} {text}".strip()

        self.current_lead_question_index = q.get("question_index", self.current_lead_question_index)
        turn_type_map = {
            "anchor": TurnType.MAIN_QUESTION.value,
            "anchor_alt": TurnType.MAIN_QUESTION.value,
            "escalation": TurnType.FOLLOW_UP.value,
            "intro": TurnType.SELF_INTRO_PROMPT.value,
            "welcome": TurnType.GREETING.value,
            "candidate_qa": TurnType.CANDIDATE_QUESTION.value,
            "closing": TurnType.CLOSING.value,
        }
        await self.speak(
            text=text,
            turn_type=turn_type_map.get(step["kind"], TurnType.MAIN_QUESTION.value),
            question_id=q.get("id"),
            phase=phase,
        )

    async def begin_interview(self) -> None:
        async with self.lock:
            if self.has_begun:
                return
            self.has_begun = True
        self.pacing.started_monotonic = time.monotonic()
        self.pacing.mark_question_started()

        is_resume = False
        resume_idx = 0
        try:
            async with AsyncSessionLocal() as db:
                s_row = (await db.execute(select(InterviewSession).where(InterviewSession.id == self.session_id))).scalars().first()
                if s_row:
                    is_resume = s_row.status == "paused" and s_row.paused_at is not None
                    s_row.status = "in_progress"
                    s_row.paused_at = None
                    if not s_row.started_at:
                        s_row.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    if is_resume:
                        resume_idx = s_row.current_question_index or 0
                    await db.commit()
        except Exception as exc:
            logger.debug(f"[simple] begin session DB notice: {exc}")

        # Resume (Part C1): map the persisted leading question index back to a script
        # step. RESUME_PROBES=false means no probes are re-asked on resume: we jump to
        # the first planned step at/after the persisted index.
        resume_step = -1
        if is_resume:
            for i, st in enumerate(self.steps):
                if st["kind"] in ("welcome", "intro"):
                    continue
                qi = (st["q"].get("question_index") or 0)
                if resume_step < 0 and qi >= resume_idx:
                    resume_step = i
        if resume_step >= 0:
            self._step = resume_step - 1
            logger.info(f"[simple] resuming paused session at step {resume_step}")
            await self.speak(
                text=f"Welcome back, {self.candidate_name}! Let's pick up right where we left off.",
                turn_type=TurnType.GREETING.value,
                phase=InterviewPhase.DEEP_DIVE,
            )
            await self._ask_step(resume_step)
            self._start_silence_monitor()
            return

        logger.info(f"[simple] scripted interview begin: {len(self.steps)} steps")
        if self.welcome_q:
            # R3.5b welcome flow: the welcome (greeting, AI disclosure, duration,
            # monitoring notice, agenda) is ONE utterance ending in "Ready to begin?".
            # The gate then waits for yes/ready/ok; the intro question is a SEPARATE
            # utterance spoken only after the acknowledgment.
            intro_idx = next((i for i, s in enumerate(self.steps) if s["kind"] == "intro"), 1)
            self._step = intro_idx  # route the NEXT advance to the intro step
            self.asked_ledger.append(
                {"step_kind": "welcome", "question_id": self.welcome_q.get("id"), "at": time.time(), "seq": self._next_sequence()}
            )
            self._awaiting_ready = True
            self._welcome_gate_reprompted = False
            self._welcome_gate_started = time.monotonic()
            await self.speak(
                self._build_greeting_text(),
                TurnType.GREETING.value,
                question_id=self.welcome_q.get("id"),
                phase=InterviewPhase.GREETING,
            )
        elif self.steps:
            await self._ask_step(0)
        self._start_silence_monitor()

    # ------------------------------------------------------------ callbacks

    def record_stt_interim(self, interim_text: str) -> None:
        """Live candidate words -> UI + answer accumulation + commit phrase."""
        text = (interim_text or "").strip()
        if not text:
            return

        # Welcome ready-gate: listen for acknowledgment (yes / ready / ok ...) or repeat request.
        if self._awaiting_ready:
            if _REPEAT_RE.search(text):
                self.session_trace.log_stt(lane="ready_gate", text=f"<repeat: {text}>", is_final=True, latency_ms=0.0)
                asyncio.create_task(
                    self.speak(
                        self._build_greeting_text(),
                        TurnType.GREETING.value,
                        question_id=self.welcome_q.get("id") if self.welcome_q else None,
                        phase=InterviewPhase.GREETING,
                    )
                )
                return
            if _READY_ACK_RE.search(text):
                self._awaiting_ready = False
                self.session_trace.log_stt(
                    lane="ready_gate",
                    text=text,
                    is_final=True,
                    latency_ms=round((time.monotonic() - getattr(self, "_welcome_gate_started", time.monotonic())) * 1000.0, 1),
                )
                asyncio.create_task(self._ready_gate_satisfied())
            return

        try:
            self._turn_text = stitch_sliding_text(self._turn_text, text)
        except Exception:
            self._turn_text = f"{self._turn_text} {text}".strip()
        self._last_activity_monotonic = time.monotonic()

        remaining, phrase = _strip_commit_phrases(self._turn_text)
        if phrase and not getattr(self, "_is_committing", False) and self.state == self.ST_LISTENING:
            self._is_committing = True
            self.state = self.ST_COMMITTED
            self._turn_text = remaining
            self._commit_reason = "phrase"
            asyncio.create_task(self.commit_turn(reason="phrase"))
        elif _REPEAT_RE.search(text) and len(text.split()) <= 8 and not getattr(self, "_is_committing", False) and self.state == self.ST_LISTENING:
            self._is_committing = True
            self.state = self.ST_COMMITTED
            self._commit_reason = "phrase"
            asyncio.create_task(self.commit_turn(reason="phrase"))

        # Emit the FULL cumulative transcript for this question so user sees their words live without disappearance
        asyncio.create_task(self._emit("candidate-speech-transcript", {"text": self._turn_text, "is_final": False}))

    def record_stt_final_chunk(self, chunk_text: str, seq: int) -> None:
        """Provider segment final (verbatim, punctuated) -> durable chunk."""
        text = (chunk_text or "").strip()
        if not text:
            return
        self._turn_chunks.append(text)
        self._turn_text = stitch_sliding_text(self._turn_text, text)
        asyncio.create_task(
            self._emit("candidate-speech-transcript", {"text": self._turn_text, "is_final": True, "seq": seq})
        )
        self.session_trace.log_stt(
            lane="provider_final_chunk",
            text=text,
            is_final=True,
            latency_ms=0.0,
            seq=seq,
        )

    def record_stt_final(self, text: str, stt_ms: float, smart_prob: Optional[float] = None, seq: Optional[int] = None, *args) -> None:
        """Legacy final callback (window final from the STT service) -> same accumulation."""
        clean = (text or "").strip()
        if not clean:
            return
        if clean not in self._turn_chunks:
            self._turn_chunks.append(clean)
            self._turn_text = stitch_sliding_text(self._turn_text, clean)
        asyncio.create_task(
            self._emit("candidate-speech-transcript", {"text": self._turn_text, "is_final": True, "seq": seq or 0})
        )
        self.session_trace.log_stt(lane="window_final_cb", text=clean, is_final=True, latency_ms=stt_ms, seq=seq or 0)

    def record_tts_first_audio(self, tts_ms: float) -> None:
        self.session_trace.log_tts(turn_id="", action="first_audio", text="", latency_ms=tts_ms)

    # ------------------------------------------------------------- commit

    async def _ready_gate_satisfied(self) -> None:
        """Ready acknowledged -> cancel the silence monitor nudge path and ask the intro."""
        self._awaiting_ready = False
        self.state = self.ST_COMMITTED
        self._turn_text = ""
        self._turn_chunks = []
        if self._stt_service is not None and hasattr(self._stt_service, "reset_turn"):
            self._stt_service.reset_turn()
        self._last_activity_monotonic = time.monotonic()
        self._welcome_gate_reprompted = False
        intro_idx = next((i for i, s in enumerate(self.steps) if s["kind"] == "intro"), None)
        if intro_idx is None:
            intro_idx = min(1, len(self.steps) - 1) if self.steps else 0
        intro_q = self.steps[intro_idx]["q"] if 0 <= intro_idx < len(self.steps) else None
        self.current_lead_question_index = (intro_q or {}).get("question_index", 0)
        await self._ask_step(intro_idx)

    async def commit_turn(self, reason: str = "button") -> Dict[str, Any]:
        """Commit the candidate's current answer (button / phrase / silence)."""
        if not self.has_begun or self.is_completed:
            return {"status": "ignored", "detail": "not-active"}
        if self.state == self.ST_ASKING and self.is_speaking and not ALLOW_BARGE_IN:
            return {"status": "ignored", "detail": "ai_speaking"}
        if getattr(self, "_is_committing", False):
            return {"status": "ignored", "detail": "already-committing"}
        if self.state == self.ST_COMMITTED and time.monotonic() - self._last_commit_monotonic < 6.0:
            return {"status": "ignored", "detail": "already-committed"}
        if time.monotonic() - self._last_commit_monotonic < 0.6:
            return {"status": "ignored", "detail": "debounce"}

        async with self._commit_lock:
            if getattr(self, "_is_committing", False) and self.state == self.ST_COMMITTED:
                return {"status": "ignored", "detail": "already-committing"}
            self._is_committing = True
            self.state = self.ST_COMMITTED
            self._last_commit_monotonic = time.monotonic()

            try:
                # Welcome ready-gate: the button (or any commit trigger) counts as "yes".
                if self._awaiting_ready:
                    self.session_trace.log_stt(lane="ready_gate", text=f"<{reason}>", is_final=True, latency_ms=0.0)
                    await self._ready_gate_satisfied()
                    return {"status": "committed", "detail": "ready-gate"}

                t0 = time.perf_counter()
                # A pending silence-commit timer is now obsolete: the commit already happened.
                if self._auto_commit_task and not self._auto_commit_task.done():
                    self._auto_commit_task.cancel()
                    self._auto_commit_task = None
                # UI: "finishing..." ring immediately.
                await self._emit("interview-bot-state", {"state": "finishing", "commit_reason": reason})

                # R3.5b: the answer of record is the analyzer's FINALIZED text — volatile
                # partials are display-only. Finalize through the last audio and give the
                # final <= 1s to land; stitched partials remain only as the logged fallback.
                partials_text = self._turn_text
                finalize_ms = 0.0
                finalize_source = "none"
                finalized_text = None
                if self._stt_service is not None and hasattr(self._stt_service, "flush_and_wait"):
                    try:
                        t_fin = time.perf_counter()
                        flushed = await self._stt_service.flush_and_wait(timeout=1.0)
                        finalize_ms = round((time.perf_counter() - t_fin) * 1000.0, 1)
                        finalize_source = getattr(self._stt_service, "last_finalize_source", "none")
                        if flushed:
                            finalized_text = flushed
                            self._turn_text = stitch_sliding_text(self._turn_text, flushed)
                    except Exception:
                        finalize_source = "error"

                assembled = self._turn_text.strip()
                phrase_spoken = False
                if self._commit_reason == "phrase":
                    assembled = _remove_commit_phrase(assembled)
                    phrase_spoken = True
                self._commit_reason = None

                words = _word_count(assembled)
                cur = self.steps[self._step] if 0 <= self._step < len(self.steps) else None
                question_id = (cur or {}).get("q", {}).get("id")
                provider = getattr(self._stt_service, "_provider_name", None) or "legacy"

                speech_ms = (
                    round((time.monotonic() - self._speech_started_monotonic) * 1000.0, 1)
                    if self._speech_started_monotonic
                    else 0.0
                )
                stt_ms = getattr(self._stt_service, "last_stt_final_ms", None)
                await self.persist_turn(
                    turn_type=TurnType.CANDIDATE_ANSWER.value,
                    speaker="candidate",
                    text=assembled or _EMPTY_ANSWER_SEQUENCE_SENTINEL,
                    question_id=question_id,
                    stt_final_ms=stt_ms,
                    provider=provider,
                    commit_reason=reason,
                    speech_duration_ms=speech_ms,
                )
                if (assembled or "").strip() == _EMPTY_ANSWER_SEQUENCE_SENTINEL:
                    await self.persist_turn(
                        turn_type=TurnType.CANDIDATE_ANSWER.value,
                        speaker="candidate",
                        text="",
                        question_id=question_id,
                        provider=provider,
                        commit_reason=f"{reason}:empty",
                    )

                # Reset accumulation for the next turn.
                self._turn_text = ""
                self._turn_chunks = []
                if self._stt_service is not None and hasattr(self._stt_service, "reset_turn"):
                    self._stt_service.reset_turn()
                self._speech_started_monotonic = None
                self._speech_active = False
                self._last_commit_monotonic = time.monotonic()
                self._commits_total += 1
                self.state = self.ST_COMMITTED
                commit_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                cadence: Dict[str, Any] = {}
                if self._stt_service is not None and hasattr(self._stt_service, "cadence_stats"):
                    try:
                        cadence = self._stt_service.cadence_stats() or {}
                    except Exception:
                        cadence = {}
                await self._emit(
                    "interview-committed",
                    {
                        "words": words,
                        "commit_ms": commit_ms,
                        "reason": reason,
                        "provider": provider,
                        "question_id": question_id,
                        "finalize_source": finalize_source,
                        "finalize_ms": finalize_ms,
                        **cadence,
                    },
                )
                self.session_trace.log_commit(
                    turn_id="",
                    reason=reason,
                    full_answer=assembled,
                    word_count=words,
                    speech_duration_s=max(0.0, speech_ms / 1000.0),
                    partials_text=partials_text,
                    finalized_text=finalized_text,
                    finalize_source=finalize_source,
                    finalize_ms=finalize_ms,
                    partial_count=cadence.get("partial_count"),
                    first_caption_ms=cadence.get("first_caption_ms"),
                    avg_partial_interval_ms=cadence.get("avg_partial_interval_ms"),
                    max_partial_interval_ms=cadence.get("max_partial_interval_ms"),
                )

                # Empty/ultra-short handling and next-step routing (rule based, no LLM).
                await self._route_after_answer(reason, words, assembled, question_id)
                return {"status": "committed", "commit_ms": commit_ms, "words": words, "provider": provider}
            finally:
                self._is_committing = False

    async def _route_after_answer(self, reason: str, words: int, assembled: str, question_id: Optional[str]) -> None:
        step = self.steps[self._step] if 0 <= self._step < len(self.steps) else None
        if step is None:
            await self._finish_flow()
            return

        gi = step.get("skill_idx", -1)
        sstate = self.skill_state.setdefault(gi, {"used_anchor_alt": False, "short_prompt_used": False, "answered": 0, "kinds": []})

        # Priority 1: Check if candidate asked to repeat or clarify question.
        # MUST happen before kind checks so candidates can ask to repeat intro, anchors, candidate_qa, etc.!
        if _REPEAT_RE.search(assembled):
            logger.info(f"[simple] repeat requested by candidate: '{assembled}'")
            await self.repeat_current_question()
            return

        # Candidate Q&A step: candidate asked questions or gave suggestions
        if step["kind"] == "candidate_qa":
            await self.speak(
                "Thank you for sharing your thoughts and questions! Our engineering team will be excited to discuss those in detail with you.",
                TurnType.CLOSING.value,
                phase=InterviewPhase.CLOSING,
            )
            await self._ask_step(self._step + 1)
            return

        # Closing/welcome/intro steps just advance.
        if step["kind"] in ("closing", "welcome", "intro"):
            await self._advance_after_bridge(step, gi)
            return

        empty = words == 0
        very_short = 0 < words < _SHORT_ANSWER_WORDS

        # Rule 1: empty answer -> prompt once, then move on.
        if empty:
            self._empty_prompt_count += 1
            if self._empty_prompt_count <= 1:
                await self.speak(_SHORT_PROMPT, TurnType.CLARIFICATION.value, question_id=question_id, phase=self.current_phase)
                return
            await self.speak("No problem.", TurnType.SILENCE_NUDGE.value, question_id=question_id)
            sstate["answered"] += 1
            await self._advance_after_bridge(step, gi)
            return

        # Rule 2: "no experience" on the anchor -> alternate anchor (verbatim), once per skill.
        if step["kind"] == "anchor" and not sstate["used_anchor_alt"] and gi >= 0:
            alt = self.skill_groups[gi].get("anchor_alt") if 0 <= gi < len(self.skill_groups) else None
            if alt and _NO_EXPERIENCE_RE.search(assembled):
                sstate["used_anchor_alt"] = True
                alt_text = (alt.get("question_text") or "").strip()
                if alt_text:
                    logger.info(f"[simple] no-experience detected -> anchor_alt for skill {gi}")
                    bridge = _BRIDGES[min(self._commits_total, len(_BRIDGES) - 1)]
                    await self.speak(f"{bridge} {alt_text}".strip(), TurnType.MAIN_QUESTION.value, question_id=alt.get("id"), phase=InterviewPhase.DEEP_DIVE)
                    # The alternate anchor CONSUMES the remaining question slot for this
                    # skill: anchor -> anchor_alt is the whole noscript path.
                    sstate["answered"] = QUESTIONS_PER_SKILL
                    return

        # Rule 3: short answer -> one gentle prompt.
        if very_short and not sstate["short_prompt_used"]:
            sstate["short_prompt_used"] = True
            await self.speak(_SHORT_PROMPT, TurnType.CLARIFICATION.value, question_id=question_id, phase=self.current_phase)
            return

        # Normal path: count the answer and move on.
        sstate["answered"] += 1
        self._empty_prompt_count = 0
        await self._advance_after_bridge(step, gi)

    async def _advance_after_bridge(self, cur_step: Dict[str, Any], gi: int) -> None:
        """Bridge (<= 3 words) then the next scripted step; skill transitions <= 12 words.

        Time-skip rule: if the clock is nearly out (closing reserve), jump straight to
        candidate Q&A + closing instead of squeezing in more questions.
        """
        bridged = _BRIDGES[min(self._commits_total, len(_BRIDGES) - 1)]
        # Time-skip escalation: shed the remaining skill sections when under ~90s
        # remain — ONLY when the immediate next step is still inside a skill section.
        remaining = self.pacing.remaining_seconds()
        next_idx = self._step + 1
        next_step = self.steps[next_idx] if next_idx < len(self.steps) else None
        if remaining < 90.0 and next_step is not None and next_step["skill_idx"] >= 0:
            qa_idx = next((i for i, s in enumerate(self.steps) if s["kind"] == "candidate_qa"), None)
            logger.info(f"[simple] time-skip escalation ({remaining:.0f}s left): shedding remaining skill sections")
            await self.speak(bridged, TurnType.SILENCE_NUDGE.value, phase=self.current_phase)
            if qa_idx is not None:
                await self._ask_step(qa_idx)
            else:
                await self._finish_flow()
            return
        # Keep going inside this skill while slots remain (anchor -> escalation).
        # anchor_alt consumed the skill's second slot -> shed its escalation step.
        if gi >= 0 and cur_step["kind"] == "anchor":
            sstate = self.skill_state.get(gi, {})
            if sstate.get("used_anchor_alt"):
                next_idx = self._step + 1
                while next_idx < len(self.steps) and self.steps[next_idx]["skill_idx"] == gi and self.steps[next_idx]["kind"] == "escalation":
                    next_idx += 1
                logger.info(f"[simple] anchor_alt consumed skill {gi}; shedding its escalation step")
                await self.speak(bridged, TurnType.SILENCE_NUDGE.value, phase=self.current_phase)
                await self._ask_step(next_idx)
                return
        if gi >= 0 and cur_step["kind"] == "anchor" and QUESTIONS_PER_SKILL > 1:
            sstate = self.skill_state.get(gi, {})
            if sstate.get("answered", 0) < QUESTIONS_PER_SKILL:
                esc_idx = next((i for i, s in enumerate(self.steps) if s["kind"] == "escalation" and s["skill_idx"] == gi), None)
                if esc_idx is not None:
                    esc_q = self.steps[esc_idx]["q"]
                    esc_text = (esc_q.get("question_text") or "").strip()
                    if esc_text:
                        logger.info(f"[simple] skill {gi} escalation question")
                        # Route FUTURE answers against the escalation step (not the anchor).
                        self._step = esc_idx
                        self.asked_ledger.append({"step_kind": "escalation", "question_id": esc_q.get("id"), "at": time.time(), "seq": self._next_sequence()})
                        await self.speak(f"{bridged} {esc_text}".strip(), TurnType.FOLLOW_UP.value, question_id=esc_q.get("id"), phase=InterviewPhase.DEEP_DIVE)
                        if self._stt_service is not None:
                            self._stt_service.last_ai_speech = esc_text
                        return
        await self.speak(bridged, TurnType.SILENCE_NUDGE.value, phase=self.current_phase)
        await self._ask_step(self._step + 1)

    async def repeat_current_question(self) -> str:
        step = self.steps[self._step] if 0 <= self._step < len(self.steps) else None
        if not step:
            return ""
        q = step.get("q", {})
        text = (q.get("question_text") or "").strip()
        if not text:
            return ""
        logger.info(f"[simple] repeating current question for step {self._step}: {text}")
        self._turn_text = ""
        self._turn_chunks = []
        if self._stt_service is not None and hasattr(self._stt_service, "reset_turn"):
            self._stt_service.reset_turn()
        await self._emit("candidate-speech-transcript", {"text": "", "is_final": True})
        repeat_phrase = f"Sure! Let me repeat the question: {text}"
        if self._stt_service is not None:
            self._stt_service.last_ai_speech = repeat_phrase
        await self.speak(repeat_phrase, TurnType.CLARIFICATION.value, question_id=q.get("id"), phase=self.current_phase)
        return repeat_phrase

    async def _finish_flow(self) -> None:
        """Closing speech done -> mark completed; post-interview evaluation runs after the loop."""
        if self.is_completed:
            return
        self.is_completed = True
        self.state = self.ST_COMMITTED
        self.current_phase = InterviewPhase.COMPLETED
        await self._emit("interview-bot-state", {"state": "finished"})
        await self._emit("interview-phase-change", {"phase": InterviewPhase.COMPLETED.value, "status": "completed"})
        try:
            async with AsyncSessionLocal() as db:
                s_row = (await db.execute(select(InterviewSession).where(InterviewSession.id == self.session_id))).scalars().first()
                if s_row:
                    s_row.status = "completed"
                    s_row.current_phase = InterviewPhase.COMPLETED.value
                    s_row.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    s_row.running_summary = self.running_summary
                    await db.commit()
        except Exception as exc:
            logger.debug(f"[simple] completion DB notice: {exc}")
        logger.info(f"[simple] interview flow complete for {self.session_id}; triggering post-interview evaluation")
        try:
            async with AsyncSessionLocal() as db:
                await evaluate_interview_session(self.session_id, db)
        except Exception as exc:
            logger.error(f"[simple] post-interview evaluation error: {exc}")

    # ------------------------------------------------------------ auto commit

    def _schedule_auto_commit(self) -> None:
        if self._auto_commit_task and not self._auto_commit_task.done():
            return
        self._auto_commit_task = asyncio.create_task(self._auto_commit_after_silence())

    async def _auto_commit_after_silence(self) -> None:
        """AUTO_COMMIT_SILENCE: commit once the candidate has been idle for the window.

        Re-arms past late STT finals (which legitimately count as activity) instead of
        firing at a fixed 2.5s after the user stopped — the analyzer's window final
        routinely lands ~0.5-1.5s after the VAD stop, so a single fixed deadline kept
        failing its idle check and silence commits were skipped entirely.
        The task is still bounded (window + 2s slack).
        """
        wait = max(1.0, AUTO_COMMIT_SILENCE_SECS)
        max_extension = 2.0  # bounded slack for late activity frames
        t_start = time.monotonic()
        try:
            while time.monotonic() - t_start < wait + max_extension:
                if self.state != self.ST_LISTENING or self._speech_active:
                    return
                if time.monotonic() - self._last_activity_monotonic >= wait - 0.35:
                    break
                await asyncio.sleep(0.2)
            if self.state == self.ST_LISTENING and not self._speech_active:
                await self._emit("interview-bot-state", {"state": "finishing", "commit_reason": "silence"})
            if (
                time.monotonic() - self._last_activity_monotonic >= wait - 0.35
                and self.state == self.ST_LISTENING
                and not self._speech_active
            ):
                logger.info("[simple] AUTO_COMMIT_SILENCE reached; committing turn")
                await self.commit_turn(reason="silence")
        except asyncio.CancelledError:
            pass

    # ---------------------------------------------------------- silence nudges

    def _start_silence_monitor(self) -> None:
        if self._silence_task and not self._silence_task.done():
            return
        self._silence_task = asyncio.create_task(self._silence_monitor_loop())

    async def _silence_monitor_loop(self) -> None:
        """LISTENING silence: one nudge, then repeat the question (rule-based)."""
        try:
            while not self.is_completed:
                await asyncio.sleep(5.0)
                if self.state != self.ST_LISTENING or self.is_speaking:
                    continue
                idle = time.monotonic() - self._last_activity_monotonic

                # Welcome ready-gate: re-prompt once, then proceed without the ack.
                if self._awaiting_ready:
                    if idle < _WELCOME_GATE_SILENCE_SECS:
                        continue
                    if not self._welcome_gate_reprompted:
                        self._welcome_gate_reprompted = True
                        await self.speak(
                            "Just say yes whenever you're ready to begin.",
                            TurnType.SILENCE_NUDGE.value,
                            question_id=self.welcome_q.get("id") if self.welcome_q else None,
                            phase=InterviewPhase.GREETING,
                        )
                        self._last_activity_monotonic = time.monotonic()
                    else:
                        logger.info("[simple] welcome gate unanswered twice; proceeding to intro")
                        self._awaiting_ready = False
                        await self._ready_gate_satisfied()
                    continue

                if idle < SILENCE_NUDGE_SECS:
                    continue
                if self._silence_nudges == 0:
                    self._silence_nudges += 1
                    await self.speak(_SHORT_PROMPT + " Or would you like me to repeat the question?", TurnType.SILENCE_NUDGE.value)
                    self._last_activity_monotonic = time.monotonic()
                elif self._silence_nudges == 1:
                    self._silence_nudges += 1
                    await self.repeat_current_question()
                    self._last_activity_monotonic = time.monotonic()
                else:
                    break
        except asyncio.CancelledError:
            pass

    # ---------------------------------------------------------------- frames

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        try:
            await super().process_frame(frame, direction)
        except Exception:
            pass

        if isinstance(frame, UserStartedSpeakingFrame):
            self._last_activity_monotonic = time.monotonic()
            if self._auto_commit_task and not self._auto_commit_task.done():
                self._auto_commit_task.cancel()
            if self.is_speaking:
                # ALLOW_BARGE_IN=false (default): never stop the bot mid-question.
                if not ALLOW_BARGE_IN:
                    await self._emit("interview-bot-state", {"state": "ai_speaking_wait"})
                return await self.push_frame(frame, direction)
            self._speech_active = True
            self._speech_started_monotonic = time.monotonic()
            self.state = self.ST_LISTENING
            self._silence_nudges = 0
            await self._emit("interview-bot-state", {"state": "listening"})

        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._last_activity_monotonic = time.monotonic()
            if self._speech_active:
                self._speech_active = False
                if self.state == self.ST_LISTENING:
                    idle_wait = max(1.0, AUTO_COMMIT_SILENCE_SECS)
                    logger.info(f"[simple] speech ended; auto-commit in {idle_wait}s (button/phrase can commit sooner)")
                    self._schedule_auto_commit()

        elif isinstance(frame, InterimTranscriptionFrame):
            text = (getattr(frame, "text", "") or "").strip()
            if text:
                self.record_stt_interim(text)

        elif isinstance(frame, TranscriptionFrame):
            text = (getattr(frame, "text", "") or "").strip()
            if text:
                self._last_activity_monotonic = time.monotonic()
                if self._stt_service is None or not hasattr(self._stt_service, "on_final_chunk"):
                    self.record_stt_final_chunk(text, seq=getattr(self, "_commits_total", 0))

        elif isinstance(frame, (BotStartedSpeakingFrame, TTSStartedFrame)):
            self.is_speaking = True
            self.state = self.ST_ASKING
            if self._stt_service is not None and hasattr(self._stt_service, "set_bot_speaking"):
                self._stt_service.set_bot_speaking(True)
            if self._stt_service is not None and hasattr(self._stt_service, "last_ai_speech"):
                self._stt_service.last_ai_speech = self.last_ai_speech
            self._last_activity_monotonic = time.monotonic()
            await self._emit("interview-bot-state", {"state": "speaking"})

        elif isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame)):
            self.is_speaking = False
            if self._stt_service is not None and hasattr(self._stt_service, "set_bot_speaking"):
                self._stt_service.set_bot_speaking(False)
            self._last_activity_monotonic = time.monotonic()
            if self.state == self.ST_ASKING:
                self.state = self.ST_LISTENING
                self._is_committing = False
            await self._emit("interview-bot-state", {"state": "listening"})

        elif isinstance(frame, InterruptionFrame):
            # Simple mode never halts bot audio via VAD interruptions.
            return

        await self.push_frame(frame, direction)

    # ---------------------------------------------------------------- cleanup

    async def cleanup(self) -> None:
        for t in (self._auto_commit_task, self._silence_task, self._stt_wait_task):
            if t and not t.done():
                t.cancel()
