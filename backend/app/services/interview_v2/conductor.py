"""Interview Conductor (v2).

A pure, deterministic reducer managing the runtime interview script,
autonomous answer completion, speculative replies, pacing, and half-duplex state.

Signature:
    step(state: ConductorState, event: ConductorEvent) -> Tuple[ConductorState, List[ConductorEffect]]

Characteristics:
- 100% pure reducer: no I/O, no LLM calls, no wall-clock reads (all timestamps arrive via event.now_ms).
- Grounded in real plan data from plan_materializer.py / state_machine.py:
    welcome -> ready gate -> intro -> per skill: anchor, one follow-up (anchor_alt or escalation) -> candidate Q&A -> closing.
- High-speed autonomous completion:
    COMPLETE answers commit after ~300ms grace.
    INCOMPLETE answers commit after ~2500ms grace.
    EagerEndOfTurn triggers speculative reply. TurnResumed / TurnStart cancels speculation.
    Late TurnStart before BotAudioStarted un-commits and merges back into buffer.
    700ms silence after commit plays rotating conversational bridge once.
- 100% serializable state for robust reconnection.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import unicodedata
import uuid

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Decision Context Identity & Content Hashing (Phase A6)
# -----------------------------------------------------------------------------

def normalize_text_for_hash(text: str) -> str:
    """Canonical normalization for answer & question hashing and verbatim runs.
    1. Unicode NFKC normalization
    2. Lowercase (case-insensitive)
    3. Strip punctuation
    4. Collapse contiguous whitespace
    """
    if not text:
        return ""
    norm = unicodedata.normalize("NFKC", text).strip().lower()
    norm = re.sub(r"[^\w\s]", "", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def compute_content_hash(text: str) -> str:
    """Compute sha256 hex digest of canonically normalized text."""
    canonical = normalize_text_for_hash(text)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def has_verbatim_run(ack: str, candidate_answer: str, run_length: int = 5) -> bool:
    """True if ack contains a verbatim sequence of >= run_length words from candidate_answer."""
    ack_words = normalize_text_for_hash(ack).split()
    ans_words = normalize_text_for_hash(candidate_answer).split()
    if len(ack_words) < run_length or len(ans_words) < run_length:
        return False
    for i in range(len(ack_words) - run_length + 1):
        window = ack_words[i : i + run_length]
        for j in range(len(ans_words) - run_length + 1):
            if ans_words[j : j + run_length] == window:
                return True
    return False


@dataclass(frozen=True)
class DecisionContextSnapshot:
    """Immutable context snapshot capturing turn identity, hashes, and context at request time."""
    session_id: str
    candidate_turn_id: str
    question_index: int
    skill_name: str
    phase: str
    normalized_answer: str
    answer_hash: str
    question_text: str
    question_hash: str
    request_id: str
    speculation_id: Optional[str] = None


# -----------------------------------------------------------------------------
# Authoritative Outbound Speech Ledger (Phase A6)
# -----------------------------------------------------------------------------

@dataclass
class OutboundSpeechSegment:
    """Detailed record of a single synthesized / played audio segment in a bot turn."""
    session_id: str
    candidate_turn_id: str
    event_seq: int
    speech_id: str
    request_id: str
    semantic_kind: str  # "bridge", "ack", "transition", "question", "qa_reply", "closing"
    text: str
    action: str  # raw LLM action
    effective_action: str
    raw_action: str = ""
    validated_action: str = ""
    override_reason: str = ""
    question_id: str = ""
    skill_name: str = ""
    scheduled_at_ms: float = 0.0
    sent_at_ms: float = 0.0
    playback_started_at_ms: Optional[float] = None
    playback_completed_at_ms: Optional[float] = None
    status: str = "scheduled"  # "scheduled", "included_in_outbound", "stream_sent", "playback_started", "playback_completed", "cancelled", "suppressed"
    suppression_reason: Optional[str] = None


class OutboundSpeechLedger:
    """Authoritative outbound speech ledger tracking every segment and utterance played to the user."""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.segments: List[OutboundSpeechSegment] = []
        self._seq: int = 0

    def record_segment(
        self,
        candidate_turn_id: str,
        speech_id: str,
        request_id: str,
        semantic_kind: str,
        text: str,
        action: str,
        effective_action: str,
        raw_action: str = "",
        validated_action: str = "",
        override_reason: str = "",
        question_id: str = "",
        skill_name: str = "",
        scheduled_at_ms: float = 0.0,
        status: str = "scheduled",
        suppression_reason: Optional[str] = None,
    ) -> OutboundSpeechSegment:
        self._seq += 1
        r_action = raw_action or action
        v_action = validated_action or effective_action
        seg = OutboundSpeechSegment(
            session_id=self.session_id,
            candidate_turn_id=candidate_turn_id,
            event_seq=self._seq,
            speech_id=speech_id,
            request_id=request_id,
            semantic_kind=semantic_kind,
            text=text,
            action=action,
            effective_action=effective_action,
            raw_action=r_action,
            validated_action=v_action,
            override_reason=override_reason,
            question_id=question_id,
            skill_name=skill_name,
            scheduled_at_ms=scheduled_at_ms,
            status=status,
            suppression_reason=suppression_reason,
        )
        self.segments.append(seg)
        return seg

    def mark_sent(self, speech_id: str, sent_at_ms: float) -> None:
        for s in self.segments:
            if s.speech_id == speech_id and s.status in ("scheduled", "included_in_outbound"):
                s.sent_at_ms = sent_at_ms
                s.status = "stream_sent"

    def mark_started(self, speech_id: str, started_at_ms: float, kind: Optional[str] = None) -> None:
        for s in self.segments:
            if s.speech_id == speech_id and (kind is None or s.semantic_kind == kind):
                if s.playback_started_at_ms is None:
                    s.playback_started_at_ms = started_at_ms
                    s.status = "playback_started"

    def mark_completed(self, speech_id: str, completed_at_ms: float, kind: Optional[str] = None) -> None:
        for s in self.segments:
            if s.speech_id == speech_id and (kind is None or s.semantic_kind == kind):
                s.playback_completed_at_ms = completed_at_ms
                s.status = "playback_completed"

    def mark_cancelled(self, speech_id: str) -> None:
        for s in self.segments:
            if s.speech_id == speech_id and s.status in ("scheduled", "included_in_outbound", "stream_sent", "playback_started"):
                s.status = "cancelled"

    def get_segments_for_turn(self, candidate_turn_id: str) -> List[OutboundSpeechSegment]:
        return [s for s in self.segments if s.candidate_turn_id == candidate_turn_id]

    def get_question_segment_for_turn(
        self,
        candidate_turn_id: Optional[str] = None,
        request_id: Optional[str] = None,
        min_seq: Optional[int] = None,
    ) -> Optional[OutboundSpeechSegment]:
        """Scoped accessor retrieving question segment for current turn or request.
        Does NOT fall back to global previous-question lookups.
        """
        valid_kinds = {
            "question", "closing", "qa_reply", "welcome", "intro_hook", "anchor",
            "clarify", "escalate", "probe", "hypothetical", "off_topic", "rephrase"
        }
        valid_statuses = {"sent", "included_in_outbound", "stream_sent", "playback_started", "playback_completed"}
        matches = []
        for s in self.segments:
            if s.semantic_kind in valid_kinds and s.status in valid_statuses:
                if candidate_turn_id is not None and s.candidate_turn_id != candidate_turn_id:
                    continue
                if request_id is not None and s.request_id != request_id and not s.request_id.endswith(request_id):
                    continue
                if min_seq is not None and s.event_seq < min_seq:
                    continue
                matches.append(s)
        return matches[-1] if matches else None

    def get_last_question_segment(self) -> Optional[OutboundSpeechSegment]:
        for s in reversed(self.segments):
            if s.semantic_kind in ("question", "closing", "qa_reply", "welcome", "intro_hook", "anchor", "clarify", "escalate", "probe", "hypothetical", "off_topic", "rephrase") and s.status in ("sent", "included_in_outbound", "stream_sent", "playback_started", "playback_completed"):
                return s
        return None


# -----------------------------------------------------------------------------
# Conductor Phases & Question Roles
# -----------------------------------------------------------------------------

class ConductorPhase(str, Enum):
    INIT = "init"
    WELCOME = "welcome"
    READY_GATE = "ready_gate"
    INTRO = "intro"
    SKILL_ANCHOR = "skill_anchor"
    SKILL_FOLLOWUP = "skill_followup"
    CANDIDATE_QA = "candidate_qa"
    CLOSING = "closing"
    COMPLETED = "completed"


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


# Conjunctions and conversational filler words for incomplete turn endings
FILLERS_AND_CONJUNCTIONS: Set[str] = {
    "and",
    "or",
    "so",
    "but",
    "because",
    "which",
    "like",
    "uh",
    "um",
    "you know",
    "i mean",
    "though",
    "although",
    "well",
}

# English stopwords + interview conversational words for keyword overlap matching
STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing",
    "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is",
    "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should",
    "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we",
    "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves",
    # Interview specific filler / instruction words
    "candidate", "mentions", "mention", "specifically", "indicates", "explains", "describes", "discusses",
    "experience", "knowledge", "ability", "understands", "demonstrates",
}

# Praise and evaluating words regex for decision validation
PRAISE_REGEX = re.compile(r"\b(great|awesome|fantastic|excellent|good|perfect|wonderful|nice|brilliant|impressive|well done)\b", re.IGNORECASE)
EVAL_REGEX = re.compile(r"\b(correct|right|wrong|incorrect|accurate|inaccurate|true|false)\b", re.IGNORECASE)

# Single-word affirmatives and ready indicators
READY_SINGLE_WORDS: Set[str] = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "ready",
    "ok",
    "okay",
    "begin",
    "start",
    "proceed",
    "definitely",
    "absolutely",
}

# Ready-intent phrases
READY_INTENT_PHRASES: List[str] = [
    "i'm ready",
    "im ready",
    "i am ready",
    "ready to start",
    "ready to begin",
    "ready to go",
    "let's start",
    "lets start",
    "let's begin",
    "lets begin",
    "let's go",
    "lets go",
    "sounds good",
    "yes i am",
    "yes i'm ready",
    "yes im ready",
    "yes ready",
    "all set",
    "good to go",
    "sure am",
    "yes let's do it",
    "let's do this",
    "lets do this",
    "yes sure",
    "sure let's go",
    "sure let's start",
    "sure let's begin",
    "ready when you are",
    "ready please",
    "we can begin",
    "we can start",
    "i am ready to begin",
    "i am ready to start",
    "ready whenever you are",
    "yes please",
    "sure thing",
]

# Repeat-intent phrases (< 6 words)
REPEAT_INTENT_PHRASES: List[str] = [
    "repeat",
    "can you repeat",
    "could you repeat",
    "repeat the question",
    "please repeat",
    "repeat that",
    "what was the question",
    "say that again",
    "say again",
    "pardon",
    "come again",
    "can you say that again",
    "sorry what was the question",
    "could you repeat that please",
]

# Conversational bridges (neutral fillers only, rotated, never repeated twice in a row)
BRIDGES: List[str] = [
    "Mm-hm.",
    "Right.",
    "Okay.",
]

# Rephrase-intent phrases for candidate asking for question clarification
REPHRASE_PATTERNS: List[str] = [
    "what do you mean",
    "can you rephrase",
    "could you rephrase",
    "rephrase the question",
    "please rephrase",
    "can you clarify",
    "could you clarify",
    "what does that mean",
    "i don't understand",
    "i dont understand",
    "what do you mean by that",
    "can you say that in another way",
    "could you simplify that",
    "what do you mean by",
]

# Candidate Q&A done phrases (candidate expresses no more questions)
QA_DONE_PHRASES: Set[str] = {
    "no",
    "nope",
    "nah",
    "no questions",
    "i have no questions",
    "no more questions",
    "that's all",
    "thats all",
    "that is all",
    "i'm good",
    "im good",
    "all good",
    "nothing else",
    "no that's all",
    "no thats all",
    "no that is all",
    "none",
    "nothing from my side",
    "no i'm good",
    "no im good",
    "nothing for now",
    "i think that's all",
    "i think thats all",
    "no thank you",
    "no thanks",
    "that's everything",
    "thats everything",
    "that is everything",
}

ACK_OPENERS: List[str] = [
    "Right,",
    "I see,",
    "Okay,",
    "Mm,",
    "So,",
]

# Forbidden praise, evaluation, and quality adjectives
FORBIDDEN_ACK_REGEX = re.compile(
    r"\b(great(\s+question)?|good|strong|effective(ly)?|efficient(ly)?|solid|excellent|impressive|nice|perfect|clean(ly)?|key|correct|important\s+question|interesting\s+question|awesome|fantastic|wonderful|brilliant|well\s+done)\b",
    re.IGNORECASE,
)


# -----------------------------------------------------------------------------
# Events
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionStart:
    session_id: str
    plan: Any
    now_ms: int = 0


@dataclass(frozen=True)
class TurnStart:
    now_ms: int = 0


@dataclass(frozen=True)
class EagerTurnEnd:
    text: str
    now_ms: int = 0


@dataclass(frozen=True)
class TurnResumed:
    now_ms: int = 0


@dataclass(frozen=True)
class TurnEnd:
    text: str
    turn_id: Union[int, str]
    now_ms: int = 0


@dataclass(frozen=True)
class BotAudioStarted:
    speech_id: str
    now_ms: int = 0


@dataclass(frozen=True)
class BotSpeechDone:
    speech_id: str
    now_ms: int = 0


@dataclass(frozen=True)
class Tick:
    now_ms: int = 0
    token: Optional[str] = None


@dataclass(frozen=True)
class ReadyButton:
    now_ms: int = 0


@dataclass(frozen=True)
class CommitButton:
    now_ms: int = 0


@dataclass(frozen=True)
class RepeatRequest:
    now_ms: int = 0


@dataclass(frozen=True)
class EndButton:
    now_ms: int = 0


@dataclass(frozen=True)
class DecisionReady:
    token: str
    decision: Optional[Dict[str, Any]] = None
    now_ms: int = 0
    snapshot: Optional[DecisionContextSnapshot] = None


@dataclass(frozen=True)
class AckReady:
    token: str
    text: str
    now_ms: int = 0
    action: str = ""
    no_experience: bool = False
    snapshot: Optional[DecisionContextSnapshot] = None


ConductorEvent = Union[
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
    DecisionReady,
    AckReady,
]


# -----------------------------------------------------------------------------
# Effects
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Speak:
    text: str
    speech_id: str
    ack_text: str = ""
    transition_text: str = ""
    question_text: str = ""
    kind: str = "question"  # "question", "qa_reply", "closing", "welcome", "intro_hook"
    question_id: str = ""
    skill_name: str = ""


@dataclass(frozen=True)
class SpeakAck:
    token: str
    text: str
    speech_id: str
    action: str = ""
    question_id: str = ""
    skill_name: str = ""


@dataclass(frozen=True)
class CancelSpeech:
    pass


@dataclass(frozen=True)
class RequestDecision:
    token: str
    skill: str
    question_text: str
    answer_text: str
    probes: List[Dict[str, Any]] = field(default_factory=list)
    escalation_text: str = ""
    anchor_alt_text: str = ""
    expectations: List[Any] = field(default_factory=list)
    stretch_expectations: List[Any] = field(default_factory=list)
    followups_used: int = 0
    time_left_ms: int = 0
    last_ack_opener: Optional[str] = None
    snapshot: Optional[DecisionContextSnapshot] = None


@dataclass(frozen=True)
class StartSpeculativeReply:
    token: str
    source_text: str = ""
    next_question_text: str = ""
    snapshot: Optional[DecisionContextSnapshot] = None


@dataclass(frozen=True)
class CancelSpeculativeReply:
    token: str


@dataclass(frozen=True)
class PlayBridge:
    text: str
    speech_id: str
    candidate_turn_id: str = ""


@dataclass(frozen=True)
class ScheduleTimer:
    name: str
    at_ms: int
    token: str
    delay_ms: int = 0


@dataclass(frozen=True)
class CancelTimer:
    name: str


@dataclass(frozen=True)
class Persist:
    turn: Dict[str, Any]


@dataclass(frozen=True)
class EmitUI:
    status: str
    payload: Dict[str, Any] = field(default_factory=dict)


ConductorEffect = Union[
    Speak,
    SpeakAck,
    CancelSpeech,
    RequestDecision,
    StartSpeculativeReply,
    CancelSpeculativeReply,
    PlayBridge,
    ScheduleTimer,
    CancelTimer,
    Persist,
    EmitUI,
]


# -----------------------------------------------------------------------------
# Question Plan Representation
# -----------------------------------------------------------------------------

@dataclass
class PlanQuestion:
    question_index: int
    kind: str
    skill_name: str
    question_text: str
    priority_tier: str = "P0"
    section_id: Optional[str] = None
    expected_key_points: List[str] = field(default_factory=list)
    stretch_key_points: List[str] = field(default_factory=list)
    trigger_condition: Optional[str] = None
    probe_id: Optional[str] = None

    @classmethod
    def from_raw(cls, q: Any) -> "PlanQuestion":
        if isinstance(q, dict):
            return cls(
                question_index=int(q.get("question_index", 0)),
                kind=str(q.get("kind", "")),
                skill_name=str(q.get("skill_name", "")),
                question_text=str(q.get("question_text", "")),
                priority_tier=str(q.get("priority_tier", "P0")),
                section_id=str(q.get("section_id", "")) if q.get("section_id") else None,
                expected_key_points=list(q.get("expected_key_points", [])),
                stretch_key_points=list(q.get("stretch_key_points", [])),
                trigger_condition=q.get("trigger_condition"),
                probe_id=q.get("probe_id"),
            )
        return cls(
            question_index=getattr(q, "question_index", 0),
            kind=getattr(q, "kind", ""),
            skill_name=getattr(q, "skill_name", ""),
            question_text=getattr(q, "question_text", ""),
            priority_tier=getattr(q, "priority_tier", "P0"),
            section_id=getattr(q, "section_id", None),
            expected_key_points=list(getattr(q, "expected_key_points", [])),
            stretch_key_points=list(getattr(q, "stretch_key_points", [])),
            trigger_condition=getattr(q, "trigger_condition", None),
            probe_id=getattr(q, "probe_id", None),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -----------------------------------------------------------------------------
# State
# -----------------------------------------------------------------------------

@dataclass
class ConductorState:
    session_id: str = ""
    phase: ConductorPhase = ConductorPhase.INIT

    # Script progression
    questions: List[PlanQuestion] = field(default_factory=list)
    current_question_index: int = -1
    current_skill_index: int = -1
    skill_names: List[str] = field(default_factory=list)

    # Question tracking by skill
    # skill_name -> {"anchor": PlanQuestion, "anchor_alt": PlanQuestion, "escalation": PlanQuestion, "probes": [...]}
    skill_questions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    escalation_used_for_skill: Dict[str, bool] = field(default_factory=dict)
    followups_used_per_skill: Dict[str, int] = field(default_factory=dict)
    clarify_used_per_skill: Dict[str, bool] = field(default_factory=dict)
    covered_expectations_per_skill: Dict[str, List[str]] = field(default_factory=dict)
    asked_questions_history: List[str] = field(default_factory=list)
    last_ack_opener: Optional[str] = None
    off_topic_retries_per_question: Dict[int, int] = field(default_factory=dict)
    hypothetical_used_per_skill: Dict[str, bool] = field(default_factory=dict)
    insufficient_evidence_per_skill: Dict[str, bool] = field(default_factory=dict)

    # Ack-First streaming tracking
    spoken_ack_token: Optional[str] = None
    spoken_ack_text: str = ""
    ack_playback_ended_at_ms: Optional[int] = None
    pending_question_effects: List[Any] = field(default_factory=list)
    off_topic_count_per_skill: Dict[str, int] = field(default_factory=dict)
    commit_at_ms: int = 0

    # Candidate Q&A and Job Context
    job_record: Dict[str, Any] = field(default_factory=dict)
    qa_rounds_used: int = 0
    you_mentioned_used_count: int = 0
    current_candidate_turn_id: str = ""

    # Decision identity snapshots (Phase A6)
    active_decision_snapshot: Optional[DecisionContextSnapshot] = None
    active_speculation_snapshot: Optional[DecisionContextSnapshot] = None

    # Time tracking per skill
    skill_budgets_ms: Dict[str, int] = field(default_factory=dict)
    skill_time_spent_ms: Dict[str, int] = field(default_factory=dict)
    current_skill_start_ms: int = 0

    # Dynamic question tracking
    dynamic_question_seq: int = 0

    # Decision tracking (AWAIT_DECISION sub-state)
    awaiting_decision: bool = False
    decision_token: Optional[str] = None
    decision_start_ms: int = 0
    decision_seq: int = 0

    # Accumulator buffer & turns
    answer_buffer: str = ""
    seen_turn_ids: List[str] = field(default_factory=list)
    accumulation_started_ms: int = 0
    is_accumulating: bool = False

    # Autonomous completion & Timers
    # active_timers: timer_name -> {"at_ms": int, "token": str}
    active_timers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timer_seq: int = 0

    # Speculation
    active_speculation_token: Optional[str] = None
    speculation_source_text: str = ""
    speculation_seq: int = 0

    # Bot speech & audio tracking
    active_speech_id: Optional[str] = None
    bot_speaking: bool = False
    bot_audio_started: bool = False
    speech_seq: int = 0

    # Bridge rotator
    last_bridge_index: int = -1
    bridge_played_for_commit: bool = False

    # Silence progression tracking (25s, 60s, 90s)
    question_active_at_ms: int = 0
    silence_nudge_emitted: bool = False
    silence_repeat_emitted: bool = False

    # Commit tracking
    is_committed: bool = False
    committed_answer: str = ""
    turn_counter: int = 0
    phase_before_commit: Optional[ConductorPhase] = None
    question_index_before_commit: int = -1

    # Pacing and config
    complete_grace_ms: int = 300
    incomplete_grace_ms: int = 2500
    hard_cap_ms: int = 180000
    decision_timeout_ms: int = 1500
    bridge_delay_ms: int = 700
    silence_delay_ms: int = 25000

    def copy(self) -> "ConductorState":
        return copy.deepcopy(self)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["phase"] = self.phase.value
        d["phase_before_commit"] = self.phase_before_commit.value if self.phase_before_commit else None
        d["questions"] = [q.to_dict() for q in self.questions]
        d["pending_question_effects"] = []
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConductorState":
        data = copy.deepcopy(data)
        data["phase"] = ConductorPhase(data.get("phase", ConductorPhase.INIT.value))
        pbc = data.get("phase_before_commit")
        data["phase_before_commit"] = ConductorPhase(pbc) if pbc else None
        data.setdefault("question_index_before_commit", -1)
        data["questions"] = [PlanQuestion.from_raw(q) for q in data.get("questions", [])]
        raw_sq = data.get("skill_questions", {})
        reconstructed_sq: Dict[str, Dict[str, Any]] = {}
        for skill, q_map in raw_sq.items():
            reconstructed_sq[skill] = {}
            for role, q_val in q_map.items():
                if role == "probes":
                    reconstructed_sq[skill]["probes"] = [PlanQuestion.from_raw(p) for p in q_val] if q_val else []
                elif q_val is not None:
                    reconstructed_sq[skill][role] = PlanQuestion.from_raw(q_val)
                else:
                    reconstructed_sq[skill][role] = None
        data["skill_questions"] = reconstructed_sq
        data.setdefault("awaiting_decision", False)
        data.setdefault("decision_token", None)
        data.setdefault("decision_start_ms", 0)
        data.setdefault("decision_seq", 0)
        data.setdefault("followups_used_per_skill", {})
        data.setdefault("clarify_used_per_skill", {})
        data.setdefault("covered_expectations_per_skill", {})
        data.setdefault("asked_questions_history", [])
        data.setdefault("job_record", {})
        data.setdefault("qa_rounds_used", 0)
        data.setdefault("decision_timeout_ms", 1500)
        data.setdefault("skill_budgets_ms", {})
        data.setdefault("skill_time_spent_ms", {})
        data.setdefault("current_skill_start_ms", 0)
        data.setdefault("dynamic_question_seq", 0)
        data.setdefault("last_ack_opener", None)
        if "off_topic_retries_per_question" in data:
            data["off_topic_retries_per_question"] = {
                int(k): int(v) for k, v in data["off_topic_retries_per_question"].items()
            }
        else:
            data.setdefault("off_topic_retries_per_question", {})
        data.setdefault("hypothetical_used_per_skill", {})
        data.setdefault("insufficient_evidence_per_skill", {})
        data.setdefault("spoken_ack_token", None)
        data.setdefault("spoken_ack_text", "")
        data.setdefault("ack_playback_ended_at_ms", None)
        data.setdefault("pending_question_effects", [])
        data.setdefault("off_topic_count_per_skill", {})
        data.setdefault("commit_at_ms", 0)
        return cls(**data)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def get_skill_time_left_ms(state: ConductorState, skill: str, now_ms: int) -> int:
    """Compute remaining time in ms for the given skill based on budget and elapsed time."""
    budget = state.skill_budgets_ms.get(skill, 300000)  # default 5 min = 300,000 ms
    spent = state.skill_time_spent_ms.get(skill, 0)
    if state.current_skill_start_ms > 0 and now_ms >= state.current_skill_start_ms:
        spent += (now_ms - state.current_skill_start_ms)
    return max(0, budget - spent)


def check_token_overlap(text1: str, text2: str) -> float:
    """Calculate directional token overlap: |T1 & T2| / |T1|."""
    t1 = set(re.findall(r"\b\w+\b", text1.lower()))
    t2 = set(re.findall(r"\b\w+\b", text2.lower()))
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / float(len(t1))


def normalize_text(text: str) -> str:
    """Normalize text for exact comparison: collapse whitespace, lowercase, strip trailing punctuation."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    cleaned = re.sub(r"[\.,!\?;]+$", "", cleaned).strip()
    return cleaned

def classify_completeness(text: str) -> Completeness:
    """Classify accumulated answer completeness per Phase 3 rules.

    COMPLETE   = ends with . ? ! , has >= 6 words, last word is not a conjunction/filler.
    INCOMPLETE = anything else, or ends with a comma.
    """
    cleaned = text.strip()
    if not cleaned:
        return Completeness.INCOMPLETE

    if cleaned.endswith(","):
        return Completeness.INCOMPLETE

    if not cleaned.endswith((".", "?", "!")):
        return Completeness.INCOMPLETE

    words = re.findall(r"\b[\w'-]+\b", cleaned)
    if len(words) < 6:
        return Completeness.INCOMPLETE

    # Check two-word fillers (e.g. "you know", "i mean")
    if len(words) >= 2:
        last_two = f"{words[-2].lower()} {words[-1].lower()}"
        if last_two in FILLERS_AND_CONJUNCTIONS:
            return Completeness.INCOMPLETE

    # Check single-word fillers / conjunctions
    last_word = words[-1].lower()
    if last_word in FILLERS_AND_CONJUNCTIONS:
        return Completeness.INCOMPLETE

    return Completeness.COMPLETE


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def matches_ready_intent(text: str) -> bool:
    """True if text indicates candidate readiness to begin the interview."""
    if not text:
        return False
    cleaned = text.strip().lower()
    words = re.findall(r"\b[\w']+\b", cleaned)
    if not words:
        return False

    # 1. Single-word affirmative or short affirmative (<= 4 words) containing a ready keyword
    if len(words) <= 4:
        for w in words:
            if w in READY_SINGLE_WORDS:
                return True

    # 2. Explicit phrase matching
    normalized = " ".join(words)
    for phrase in READY_INTENT_PHRASES:
        if phrase in normalized:
            return True

    # 3. Action keywords in short response (<= 6 words)
    if len(words) <= 6:
        for kw in ("ready", "begin", "start", "proceed", "go ahead"):
            if kw in normalized:
                return True

    return False


def matches_repeat_intent(text: str) -> bool:
    """True if text is < 6 words and matches repeat-intent."""
    cleaned = text.strip().lower()
    words = re.findall(r"\b[\w']+\b", cleaned)
    if not words or len(words) >= 6:
        return False
    normalized = " ".join(words)
    for phrase in REPEAT_INTENT_PHRASES:
        if phrase in normalized:
            return True
    return False


def matches_rephrase_intent(text: str) -> bool:
    """True if text is short (<= 12 words) and matches rephrase or question clarification intent."""
    cleaned = text.strip().lower()
    words = re.findall(r"\b[\w']+\b", cleaned)
    if not words or len(words) > 12:
        return False
    normalized = " ".join(words)
    for phrase in REPHRASE_PATTERNS:
        if phrase in normalized:
            return True
    return False


INTRO_FILTER_WORDS: Set[str] = {
    "five", "four", "three", "two", "one", "six", "seven", "eight", "nine", "ten",
    "years", "year", "months", "month", "experience", "background", "worked", "working",
    "role", "roles", "past", "recent", "currently", "started", "company", "companies",
    "team", "teams", "myself", "sure", "hello", "well",
}


def is_qa_done_phrase(text: str) -> bool:
    """True if candidate expresses having no more questions in Candidate Q&A."""
    cleaned = normalize_text(text)
    words = re.findall(r"\b[\w']+\b", cleaned)
    if not words or len(words) > 35:
        return False
    normalized = " ".join(words).lower()
    extended_phrases = set(QA_DONE_PHRASES).union({
        "covered everything", "covers everything", "all my questions",
        "no further questions", "nothing further", "no other questions",
        "that covers it", "thats it", "that is it", "all set"
    })
    for phrase in extended_phrases:
        if normalized == phrase or normalized.startswith(f"{phrase} ") or normalized.endswith(f" {phrase}") or f" {phrase} " in f" {normalized} ":
            return True
    return False


def generate_intro_ack(answer_text: str) -> str:
    """Generate conversational intro ack quoting a concrete technology or project named by the candidate; if none, omit the ack."""
    cleaned = answer_text.strip()
    tech_matches = re.findall(
        r"\b(?:Python|asyncio|Kafka|PostgreSQL|Postgres|Docker|Kubernetes|AWS|GCP|microservices|"
        r"streaming architectures|distributed systems|Redis|Java|Go|Rust|Node|React|FastAPI|Django|Flask)\b",
        cleaned,
        re.IGNORECASE,
    )
    if tech_matches:
        tech = tech_matches[0]
        return f"Right, so your work with {tech}."
    return ""


COMMON_STOP_WORDS: Set[str] = {
    "the", "and", "that", "this", "with", "have", "from", "for", "are", "was", "were", "been", "being",
    "you", "your", "our", "their", "they", "them", "what", "when", "where", "which", "who", "whom",
    "whose", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "than", "too", "very", "can", "will", "just", "should", "now", "also", "then", "into", "onto", "over",
    "about", "above", "after", "again", "against", "because", "before", "below", "between", "down", "during",
    "further", "here", "there", "once", "only", "same", "through", "under", "until", "while", "out", "off",
    "does", "did", "doing", "would", "could", "well", "yes", "not", "but", "its", "has", "had", "say",
    "said", "one", "two", "use", "used", "using", "work", "worked", "working", "mention", "mentioned"
}


def extract_content_words(text: str) -> Set[str]:
    """Extract lowercased content words of length >= 3 excluding stop words."""
    if not text:
        return set()
    raw_words = re.findall(r"\b[a-zA-Z0-9_\'-]+\b", text.lower())
    return {w for w in raw_words if len(w) >= 3 and w not in COMMON_STOP_WORDS}


def is_ack_grounded(ack: str, candidate_answer: str, question_text: str = "") -> bool:
    """True if ack shares >= 1 content word with candidate answer that is NOT in current question text."""
    if not ack or not candidate_answer:
        return False
    ans_words = extract_content_words(candidate_answer)
    if not ans_words:
        return False
    q_words = extract_content_words(question_text)
    distinct_ans_words = ans_words - q_words
    if not distinct_ans_words:
        return False
    ack_words = extract_content_words(ack)
    shared = ack_words.intersection(distinct_ans_words)
    return len(shared) >= 1


FORBIDDEN_ACK_PHRASES: List[str] = [
    "you're curious about",
    "you are curious about",
    "you’re curious about",
    "curious about",
    "you have no experience",
    "you've got no experience",
    "you’ve got no experience",
    "no experience",
    "you noted your background",
]

COMMON_PROPER_NOUNS: Set[str] = {
    "python", "asyncio", "kafka", "postgresql", "postgres", "redis", "docker", "kubernetes",
    "aws", "gcp", "celery", "gil", "cpu", "io", "i/o", "api", "raft", "paxos", "java", "sql"
}


def format_rest_after_opener(rest: str) -> str:
    """Ensure word immediately following an opener is lowercased unless it is a proper noun/acronym."""
    if not rest:
        return ""
    words = rest.split()
    first = words[0]
    if first.lower() in COMMON_PROPER_NOUNS or first.isupper():
        return rest
    words[0] = first[0].lower() + first[1:]
    return " ".join(words)


FORBIDDEN_QA_HALLUCINATIONS: List[str] = [
    "salary", "compensation", "pay", "bonus", "401k", "equity", "stock", "benefits", "health insurance",
    "remote policy", "hybrid", "vacation", "pto", "team size", "manager", "reporting",
    "autonomy", "mentoring", "six month", "six-month", "6 month", "6-month", "success", "metric", "criteria",
    "culture", "roadmap", "timeline", "expectation",
]

APPROVED_QA_DEFERRAL: str = "I don't have that detail in our job description, but our hiring team will follow up with you on that. Anything else?"


def extract_job_facts(job_record: Dict[str, Any]) -> Dict[str, str]:
    """Extract a stable dictionary of fact_id -> fact_text from job_record."""
    facts = {}
    if not job_record:
        return facts
    if job_record.get("title"):
        facts["job_title"] = f"The job title is {job_record['title']}."
    if job_record.get("seniority"):
        facts["seniority"] = f"The seniority level is {job_record['seniority']}."
    skills = job_record.get("skills", [])
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    for idx, s in enumerate(skills, 1):
        facts[f"required_skill_{idx}"] = f"Required technical skill: {s}."
    desc = job_record.get("description", "")
    if desc:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", desc) if s.strip()]
        for idx, s in enumerate(sentences, 1):
            facts[f"description_fact_{idx:03d}"] = s
    return facts


def validate_qa_decision(
    decision: Optional[Dict[str, Any]],
    job_facts: Dict[str, str],
    candidate_question: str,
) -> Tuple[str, str, List[str]]:
    """Validate Q&A reply against stable job facts.
    Returns (effective_followup, effective_ack, verified_source_facts).
    Enforces max 2 sentences, max 35 words, and approved deferral for unsupported topics.
    Suppresses ack whenever reply defers, or if ack contains ungrounded/forbidden claims.
    """
    if not decision:
        return APPROVED_QA_DEFERRAL, "", []

    raw_followup = str(decision.get("followup") or "").strip()
    source_facts = list(decision.get("source_facts", []) or [])
    raw_ack = str(decision.get("ack") or "").strip()

    # Check for forbidden hallucinated topics in candidate question, proposed answer, or raw ack
    norm_check = re.sub(r"[-\s]+", " ", f"{candidate_question} {raw_followup} {raw_ack}".lower())
    norm_check = norm_check.replace("’", "'").replace("‘", "'")
    for forbidden in FORBIDDEN_QA_HALLUCINATIONS:
        if forbidden in norm_check:
            # Candidate asked or LLM answered/acknowledged forbidden hallucinated topic -> approved deferral!
            return APPROVED_QA_DEFERRAL, "", []

    # Check for forbidden ack phrases in raw ack
    norm_ack_check = unicodedata.normalize("NFKC", raw_ack).strip().lower().replace("’", "'").replace("‘", "'")
    for fp in FORBIDDEN_ACK_PHRASES:
        if fp in norm_ack_check:
            # Contradicting or forbidden ack -> suppress ack!
            raw_ack = ""
            break

    # Verify source facts
    if not source_facts:
        return APPROVED_QA_DEFERRAL, "", []

    valid_facts = [f for f in source_facts if f in job_facts]
    if not valid_facts:
        return APPROVED_QA_DEFERRAL, "", []

    # Check content support from cited facts (Requirement 2 & 6: source ID alone is not proof)
    cited_fact_text = " ".join(job_facts[f] for f in valid_facts).lower()
    fact_words = {w for w in re.findall(r"\b[a-zA-Z]{3,}\b", cited_fact_text) if w not in STOPWORDS}
    answer_words = {w for w in re.findall(r"\b[a-zA-Z]{3,}\b", raw_followup.lower()) if w not in STOPWORDS}
    if not fact_words.intersection(answer_words):
        return APPROVED_QA_DEFERRAL, "", []

    # Sentence-level claim verification: Every informational claim sentence in raw_followup must be supported by valid_facts
    # If a reply includes both supported and unsupported factual claims, defer!
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw_followup) if s.strip()]
    for s in sentences:
        s_lower = s.lower()
        if "anything else" in s_lower:
            continue
        s_words = {w for w in re.findall(r"\b[a-zA-Z]{3,}\b", s_lower) if w not in STOPWORDS}
        if s_words and not fact_words.intersection(s_words):
            # Sentence introduces unsupported claims not in cited job facts -> deferral!
            return APPROVED_QA_DEFERRAL, "", []

    # Check length (max 2 sentences, max 35 words)
    if len(sentences) > 2 or count_words(raw_followup) > 35:
        return APPROVED_QA_DEFERRAL, "", []

    if not raw_followup.endswith("?") and "anything else" not in raw_followup.lower():
        raw_followup = f"{raw_followup} Anything else?"

    # Validate acknowledgment against candidate_question
    effective_ack = ""
    if raw_ack:
        cand_words = extract_content_words(candidate_question)
        ack_words = extract_content_words(raw_ack)
        # Must share content words with candidate's current question, not a prior question
        if cand_words.intersection(ack_words):
            val_ack, _ = validate_and_format_ack(
                raw_ack=raw_ack,
                candidate_answer=candidate_question,
                action="qa_reply",
            )
            effective_ack = val_ack

    return raw_followup, effective_ack, valid_facts


def validate_and_format_ack(
    raw_ack: str,
    last_opener: Optional[str] = None,
    bridge_played: bool = False,
    turn_counter: int = 0,
    candidate_answer: str = "",
    question_text: str = "",
    enforce_grounding: bool = False,
    you_mentioned_used_count: int = 0,
    action: str = "",
    no_experience: bool = False,
) -> Tuple[str, Optional[str]]:
    """Validate ack string against Phase A6 Ack Validator rules:
    - Maximum 12 words, exactly one short sentence, no question mark.
    - If bridge played: suppress ack entirely (bridge_substituted_for_ack).
    - If action == 'off_topic': speak no acknowledgment.
    - If no_experience is True: speak no acknowledgment or permitted neutral line ('No problem.').
    - Reject praise / judgment / evaluating words.
    - Paraphrase gist: reject normalized verbatim run of >= 5 consecutive words from candidate answer.
    - Never use forbidden phrases ('You're curious about...', 'You have no experience...').
    - Use 'You mentioned...' at most once per interview.
    - Lowercase word immediately following conversational opener if not proper noun.
    - Opener rotation: Right, / I see, / Okay, / Mm, / So, / None (~30%), never same consecutively.
    Returns: (validated_ack, next_opener).
    """
    # Policy: Off-topic speaks NO ack (Phase A6.2 rule: strictly NO ack for off-topic)
    if action == "off_topic":
        return "", last_opener

    # Policy: No-experience uses no ack or permitted neutral line
    if no_experience:
        if raw_ack and normalize_text_for_hash(raw_ack) in ("no problem", "understood"):
            return "No problem.", last_opener
        return "", last_opener

    if not raw_ack:
        return "", last_opener

    ack_clean = raw_ack.strip().strip('"').strip("'")
    if not ack_clean:
        return "", last_opener

    # Normalize unicode curly apostrophes and NFKC
    ack_clean = unicodedata.normalize("NFKC", ack_clean).replace("’", "'").replace("‘", "'")

    # Check question mark or multi-sentence
    if "?" in ack_clean:
        return "", last_opener

    # Standalone neutral acks do not take an additional opener
    if ack_clean.lower().strip(".") in ("understood", "no problem", "got it", "i understand", "sure"):
        cleaned_neutral = f"{ack_clean.rstrip('.').capitalize()}."
        if bridge_played:
            return cleaned_neutral, last_opener
        return cleaned_neutral, None

    # Max 12 words (Phase A6 requirement)
    if count_words(ack_clean) > 12:
        return "", last_opener

    # Max 1 sentence
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", ack_clean) if s.strip()]
    if len(sentences) > 1:
        return "", last_opener

    # Check praise / judgment / quality adjectives
    if FORBIDDEN_ACK_REGEX.search(ack_clean):
        return "", last_opener

    # Check forbidden phrases
    lower_ack = ack_clean.lower()
    for fp in FORBIDDEN_ACK_PHRASES:
        if fp in lower_ack:
            return "", last_opener

    # Check verbatim run of 5+ words from candidate answer
    if candidate_answer and has_verbatim_run(ack_clean, candidate_answer, run_length=5):
        return "", last_opener

    # Check 'You mentioned...' usage limit (at most once per interview)
    if "you mentioned" in lower_ack and you_mentioned_used_count >= 1:
        return "", last_opener

    # Grounding against candidate answer and question text if requested
    if enforce_grounding and candidate_answer and not is_ack_grounded(ack_clean, candidate_answer, question_text):
        return "", last_opener

    # Identify existing opener if any
    matched_opener: Optional[str] = None
    rest_content = ack_clean
    for op in ACK_OPENERS:
        if ack_clean.lower().startswith(op.lower()):
            matched_opener = op
            rest_content = ack_clean[len(op):].strip()
            break

    # If rest of content still has praise / judgment
    if FORBIDDEN_ACK_REGEX.search(rest_content):
        return "", last_opener

    # If bridge played, strip leading opener
    if bridge_played:
        cleaned_rest = rest_content
        if cleaned_rest:
            cleaned_rest = cleaned_rest[0].upper() + cleaned_rest[1:]
        return cleaned_rest, last_opener

    # Format lowercasing after opener
    formatted_rest = format_rest_after_opener(rest_content)

    # Opener handling
    if matched_opener:
        if last_opener and matched_opener.lower() == last_opener.lower():
            # Rotate opener
            available_openers = [o for o in ACK_OPENERS if o.lower() != last_opener.lower()]
            target_opener = available_openers[turn_counter % len(available_openers)]
            final_ack = f"{target_opener} {formatted_rest}".strip()
            return final_ack, target_opener
        else:
            final_ack = f"{matched_opener} {formatted_rest}".strip()
            return final_ack, matched_opener

    # No opener in raw ack
    use_none_opener = (turn_counter % 3 == 0)
    if use_none_opener:
        cleaned_rest = formatted_rest
        if cleaned_rest:
            cleaned_rest = cleaned_rest[0].upper() + cleaned_rest[1:]
        return cleaned_rest, None
    else:
        available_openers = [o for o in ACK_OPENERS if o.lower() != (last_opener or "").lower()]
        target_opener = available_openers[turn_counter % len(available_openers)]
        final_ack = f"{target_opener} {formatted_rest}".strip()
        return final_ack, target_opener


def get_next_bridge(last_index: int) -> Tuple[str, int]:
    """Rotate bridges, never repeating the same one twice in a row."""
    next_idx = (last_index + 1) % len(BRIDGES)
    return BRIDGES[next_idx], next_idx


def get_next_plan_question(state: ConductorState) -> Optional[PlanQuestion]:
    """Determine the next question according to blueprint pacing and rules."""
    if state.phase in (ConductorPhase.WELCOME, ConductorPhase.READY_GATE):
        return next((q for q in state.questions if q.kind == "intro_hook"), None)

    if state.phase == ConductorPhase.INTRO:
        if state.skill_names:
            s0 = state.skill_names[0]
            return state.skill_questions.get(s0, {}).get("anchor") or _find_next_skill_question(state, 0)
        return next((q for q in state.questions if q.kind == "candidate_qa"), None)

    if state.phase == ConductorPhase.SKILL_ANCHOR:
        if 0 <= state.current_skill_index < len(state.skill_names):
            curr_skill = state.skill_names[state.current_skill_index]
            sq = state.skill_questions.get(curr_skill, {})
            # Prioritize probes, then escalation, then anchor_alt
            return (sq.get("probes")[0] if sq.get("probes") else None) or sq.get("escalation") or sq.get("anchor_alt")
        return None

    if state.phase == ConductorPhase.SKILL_FOLLOWUP:
        next_idx = state.current_skill_index + 1
        if next_idx < len(state.skill_names):
            next_skill = state.skill_names[next_idx]
            return state.skill_questions.get(next_skill, {}).get("anchor") or _find_next_skill_question(state, next_idx)
        return next((q for q in state.questions if q.kind == "candidate_qa"), None)

    if state.phase == ConductorPhase.CANDIDATE_QA:
        return next((q for q in state.questions if q.kind == "closing"), None)

    return None


# -----------------------------------------------------------------------------
# Pure Reducer: step(state, event) -> (new_state, effects)
# -----------------------------------------------------------------------------

def step(state: ConductorState, event: ConductorEvent) -> Tuple[ConductorState, List[ConductorEffect]]:
    """Pure reducer executing one transition of the interview conductor."""
    new_state = state.copy()
    effects: List[ConductorEffect] = []

    # 1. SessionStart
    if isinstance(event, SessionStart):
        new_state.session_id = event.session_id
        # Extract and organize questions from plan
        raw_questions: List[Any] = []
        if isinstance(event.plan, dict):
            raw_questions = event.plan.get("questions", [])
        elif isinstance(event.plan, list):
            raw_questions = event.plan
        elif hasattr(event.plan, "questions"):
            raw_questions = getattr(event.plan, "questions", [])

        questions = [PlanQuestion.from_raw(q) for q in raw_questions]
        questions.sort(key=lambda q: q.question_index)
        new_state.questions = questions

        # Index skill sections
        skill_dict: Dict[str, Dict[str, Any]] = {}
        skill_names_ordered: List[str] = []
        for q in questions:
            if q.kind in ("anchor", "anchor_alt", "escalation", "probe", "resume_probe"):
                s_name = q.skill_name or "General"
                if s_name not in skill_dict:
                    skill_dict[s_name] = {"probes": []}
                    skill_names_ordered.append(s_name)
                if q.kind == "anchor":
                    skill_dict[s_name]["anchor"] = q
                elif q.kind == "anchor_alt":
                    skill_dict[s_name]["anchor_alt"] = q
                elif q.kind == "escalation":
                    skill_dict[s_name]["escalation"] = q
                else:
                    skill_dict[s_name]["probes"].append(q)

        new_state.skill_questions = skill_dict
        new_state.skill_names = skill_names_ordered
        new_state.escalation_used_for_skill = {s: False for s in skill_names_ordered}
        new_state.followups_used_per_skill = {s: 0 for s in skill_names_ordered}
        new_state.clarify_used_per_skill = {s: False for s in skill_names_ordered}
        new_state.covered_expectations_per_skill = {s: [] for s in skill_names_ordered}
        new_state.qa_rounds_used = 0

        # Extract job_record if available in plan
        if isinstance(event.plan, dict):
            new_state.job_record = dict(event.plan.get("job_record", {}) or {})
            if "decision_timeout_ms" in event.plan:
                new_state.decision_timeout_ms = int(event.plan["decision_timeout_ms"])
            if "bridge_delay_ms" in event.plan:
                new_state.bridge_delay_ms = int(event.plan["bridge_delay_ms"])
            if "silence_delay_ms" in event.plan:
                new_state.silence_delay_ms = int(event.plan["silence_delay_ms"])
        elif hasattr(event.plan, "job_record"):
            new_state.job_record = dict(getattr(event.plan, "job_record", {}) or {})
            if hasattr(event.plan, "decision_timeout_ms"):
                new_state.decision_timeout_ms = int(getattr(event.plan, "decision_timeout_ms", 1500))
            if hasattr(event.plan, "bridge_delay_ms"):
                new_state.bridge_delay_ms = int(getattr(event.plan, "bridge_delay_ms", 700))
            if hasattr(event.plan, "silence_delay_ms"):
                new_state.silence_delay_ms = int(getattr(event.plan, "silence_delay_ms", 25000))

        # Initialize skill budgets from plan if provided, or default 5 minutes (300,000 ms) per skill
        raw_budgets = event.plan.get("skill_budgets_ms", {}) if isinstance(event.plan, dict) else {}
        new_state.skill_budgets_ms = {
            s: int(raw_budgets.get(s, 300000)) for s in skill_names_ordered
        }
        new_state.skill_time_spent_ms = {s: 0 for s in skill_names_ordered}

        # Locate Welcome question (Requirement 8: spoken welcome with role title and duration)
        welcome_q = next((q for q in questions if q.kind == "welcome"), None)
        role_title = new_state.job_record.get("title", "Software Engineer") if new_state.job_record else "Software Engineer"
        duration_mins = int(event.plan.get("duration_planned_mins", 25)) if isinstance(event.plan, dict) and event.plan.get("duration_planned_mins") else 25
        welcome_text = (
            welcome_q.question_text
            if welcome_q and welcome_q.question_text
            else f"Hi there! Welcome to your interview for the {role_title} role. We will spend about {duration_mins} minutes together today covering technical topics and your questions. Ready to begin?"
        )
        new_state.asked_questions_history = [welcome_text]

        new_state.phase = ConductorPhase.WELCOME
        new_state.current_question_index = welcome_q.question_index if welcome_q else 0
        new_state.speech_seq += 1
        speech_id = f"speech_{new_state.speech_seq}"
        new_state.active_speech_id = speech_id
        new_state.bot_speaking = True
        new_state.bot_audio_started = False

        effects.append(Speak(text=welcome_text, speech_id=speech_id))
        effects.append(EmitUI(status="welcome", payload={"question_text": welcome_text}))
        return new_state, effects

    # 2. EndButton (User requested immediate exit)
    if isinstance(event, EndButton):
        # Cancel all timers and speculation
        for timer_name in list(new_state.active_timers.keys()):
            effects.append(CancelTimer(name=timer_name))
        new_state.active_timers.clear()

        if new_state.active_speculation_token:
            effects.append(CancelSpeculativeReply(token=new_state.active_speculation_token))
            new_state.active_speculation_token = None

        effects.append(CancelSpeech())
        new_state.phase = ConductorPhase.COMPLETED
        new_state.speech_seq += 1
        end_speech_id = f"speech_{new_state.speech_seq}"
        new_state.active_speech_id = end_speech_id
        new_state.bot_speaking = True
        new_state.bot_audio_started = False

        close_text = "Thank you for taking the time to speak with me today. The interview is now concluded. Have a wonderful day!"
        effects.append(Speak(text=close_text, speech_id=end_speech_id))
        effects.append(EmitUI(status="completed", payload={"reason": "ended_by_candidate"}))
        return new_state, effects

    # 3. Ready Gate handling (ReadyButton, CommitButton, TurnEnd, or EagerTurnEnd matching ready-intent)
    if new_state.phase == ConductorPhase.READY_GATE:
        ready_detected = False
        if isinstance(event, (ReadyButton, CommitButton)):
            ready_detected = True
        elif isinstance(event, (TurnEnd, EagerTurnEnd)):
            if matches_ready_intent(event.text):
                ready_detected = True

        if ready_detected:
            # Cancel any pending silence timers
            if "silence" in new_state.active_timers:
                effects.append(CancelTimer(name="silence"))
                new_state.active_timers.pop("silence", None)

            # Cancel any pending commit timer
            if "commit" in new_state.active_timers:
                effects.append(CancelTimer(name="commit"))
                new_state.active_timers.pop("commit", None)

            # Cancel speculation if any
            if new_state.active_speculation_token:
                effects.append(CancelSpeculativeReply(token=new_state.active_speculation_token))
                new_state.active_speculation_token = None
                new_state.speculation_source_text = ""

            # Proceed to Intro
            intro_q = next((q for q in new_state.questions if q.kind == "intro_hook"), None)
            intro_text = (
                intro_q.question_text
                if intro_q
                else "To start off, could you please introduce yourself and share highlights from your key projects and experiences?"
            )
            new_state.phase = ConductorPhase.INTRO
            new_state.current_question_index = intro_q.question_index if intro_q else 1
            new_state.speech_seq += 1
            speech_id = f"speech_{new_state.speech_seq}"
            new_state.active_speech_id = speech_id
            new_state.bot_speaking = True
            new_state.bot_audio_started = False
            new_state.answer_buffer = ""
            new_state.seen_turn_ids.clear()
            new_state.is_committed = False
            new_state.is_accumulating = False
            new_state.accumulation_started_ms = 0

            effects.append(Speak(text=intro_text, speech_id=speech_id))
            effects.append(EmitUI(status="intro", payload={"question_text": intro_text}))
            return new_state, effects

    # 4. RepeatRequest handling
    is_repeat = isinstance(event, RepeatRequest)
    if not is_repeat and isinstance(event, TurnEnd) and new_state.phase not in (ConductorPhase.WELCOME, ConductorPhase.READY_GATE, ConductorPhase.COMPLETED):
        if matches_repeat_intent(event.text):
            is_repeat = True

    if is_repeat:
        # Replay current question text from state (zero model generation)
        curr_q = _get_current_question(new_state)
        if curr_q:
            # Cancel commit and silence timers
            if "commit" in new_state.active_timers:
                effects.append(CancelTimer(name="commit"))
                new_state.active_timers.pop("commit", None)
            if "silence" in new_state.active_timers:
                effects.append(CancelTimer(name="silence"))
                new_state.active_timers.pop("silence", None)
            if new_state.active_speculation_token:
                effects.append(CancelSpeculativeReply(token=new_state.active_speculation_token))
                new_state.active_speculation_token = None

            new_state.answer_buffer = ""
            new_state.seen_turn_ids.clear()
            new_state.is_accumulating = False
            new_state.accumulation_started_ms = 0
            new_state.speech_seq += 1
            repeat_speech_id = f"speech_{new_state.speech_seq}"
            new_state.active_speech_id = repeat_speech_id
            new_state.bot_speaking = True
            new_state.bot_audio_started = False

            effects.append(Speak(text=curr_q.question_text, speech_id=repeat_speech_id))
            effects.append(EmitUI(status="repeating_question", payload={"question_text": curr_q.question_text}))
            return new_state, effects

    # 4b. Rephrase handling (Mid-interview clarification)
    is_rephrase = False
    if isinstance(event, TurnEnd) and new_state.phase in (ConductorPhase.SKILL_ANCHOR, ConductorPhase.SKILL_FOLLOWUP):
        if matches_rephrase_intent(event.text):
            is_rephrase = True

    if is_rephrase:
        curr_q = _get_current_question(new_state)
        if curr_q:
            if "commit" in new_state.active_timers:
                effects.append(CancelTimer(name="commit"))
                new_state.active_timers.pop("commit", None)
            if "silence" in new_state.active_timers:
                effects.append(CancelTimer(name="silence"))
                new_state.active_timers.pop("silence", None)
            if new_state.active_speculation_token:
                effects.append(CancelSpeculativeReply(token=new_state.active_speculation_token))
                new_state.active_speculation_token = None

            new_state.answer_buffer = ""
            new_state.seen_turn_ids.clear()
            new_state.is_accumulating = False
            new_state.accumulation_started_ms = 0

            # Rephrase in simpler words with same intent without incrementing followups
            sq = new_state.skill_questions.get(curr_q.skill_name, {})
            alt_q = sq.get("anchor_alt")
            if alt_q and curr_q.kind == "anchor":
                rephrased_q = alt_q.question_text
            else:
                rephrased_q = f"In other words, {curr_q.question_text}"

            ack_phrase = "Sure, let me rephrase that."
            spoken_rephrase = f"{ack_phrase} {rephrased_q}"
            new_state.speech_seq += 1
            rephrase_speech_id = f"speech_{new_state.speech_seq}"
            new_state.active_speech_id = rephrase_speech_id
            new_state.bot_speaking = True
            new_state.bot_audio_started = False

            effects.append(Speak(text=spoken_rephrase, speech_id=rephrase_speech_id, ack_text=ack_phrase, question_text=rephrased_q))
            effects.append(EmitUI(status="rephrasing_question", payload={"question_text": rephrased_q, "ack": ack_phrase}))
            return new_state, effects

    # 5. Bot Audio Started / Done
    if isinstance(event, BotAudioStarted):
        if event.speech_id and not event.speech_id.startswith("bridge_"):
            new_state.bot_audio_started = True
            new_state.phase_before_commit = None
            # Reply audio started: cancel any pending bridge timer immediately
            if "bridge" in new_state.active_timers:
                effects.append(CancelTimer(name="bridge"))
                new_state.active_timers.pop("bridge", None)
        return new_state, effects

    if isinstance(event, BotSpeechDone):
        if event.speech_id and event.speech_id == new_state.active_speech_id:
            new_state.bot_speaking = False
            new_state.bot_audio_started = False
            new_state.active_speech_id = None

            # If this was ack speech, record playback end and speak question or schedule 500ms fallback timer
            if event.speech_id and event.speech_id.startswith("ack_speech_"):
                new_state.ack_playback_ended_at_ms = event.now_ms
                if new_state.pending_question_effects:
                    pending = new_state.pending_question_effects
                    new_state.pending_question_effects = []
                    for eff in pending:
                        if isinstance(eff, Speak):
                            new_state.active_speech_id = eff.speech_id
                            new_state.bot_speaking = True
                            new_state.bot_audio_started = False
                    effects.extend(pending)
                    return new_state, effects
                elif new_state.awaiting_decision:
                    new_state.timer_seq += 1
                    fb_token = f"ack_fb_{new_state.timer_seq}"
                    new_state.active_timers["ack_fallback"] = {"at_ms": event.now_ms + 500, "token": new_state.decision_token or fb_token}
                    effects.append(ScheduleTimer(name="ack_fallback", at_ms=event.now_ms + 500, token=new_state.decision_token or fb_token, delay_ms=500))
                    return new_state, effects

            # If this was a silence nudge speech, candidate's original silence clock continues
            if event.speech_id and event.speech_id.startswith("nudge_speech_"):
                return new_state, effects

            # If this was a silence repeat speech, candidate's original silence clock continues towards 90s
            if event.speech_id and event.speech_id.startswith("silence_repeat_speech_"):
                return new_state, effects

            # After Welcome speech finishes -> transition to READY_GATE
            if new_state.phase == ConductorPhase.WELCOME:
                new_state.phase = ConductorPhase.READY_GATE
                effects.append(EmitUI(status="waiting_for_ready", payload={"prompt": "Candidate can click Ready or say they are ready"}))
                return new_state, effects

            # After Closing speech finishes -> transition to COMPLETED
            if new_state.phase == ConductorPhase.CLOSING:
                new_state.phase = ConductorPhase.COMPLETED
                effects.append(EmitUI(status="completed", payload={"message": "Interview session finished"}))
                return new_state, effects

            # Normal question speech done: candidate's turn begins
            new_state.question_active_at_ms = event.now_ms
            new_state.silence_nudge_emitted = False
            new_state.silence_repeat_emitted = False
            new_state.answer_buffer = ""
            new_state.seen_turn_ids.clear()
            new_state.is_committed = False
            new_state.is_accumulating = False
            new_state.accumulation_started_ms = 0

            # Schedule silence nudge timer at 25s (or configured silence_delay_ms)
            s_delay = getattr(new_state, "silence_delay_ms", 25000) or 25000
            new_state.timer_seq += 1
            silence_token = f"silence_{new_state.timer_seq}"
            new_state.active_timers["silence"] = {"at_ms": event.now_ms + s_delay, "token": silence_token}
            effects.append(ScheduleTimer(name="silence", at_ms=event.now_ms + s_delay, token=silence_token, delay_ms=s_delay))

        return new_state, effects

    # 6. TurnStart (Candidate began speaking)
    if isinstance(event, TurnStart):
        # Cancel silence timer since candidate is speaking
        if "silence" in new_state.active_timers:
            effects.append(CancelTimer(name="silence"))
            new_state.active_timers.pop("silence", None)

        # Late TurnStart after commit but before BotAudioStarted:
        # "If TurnStart arrives after commit but before BotAudioStarted: CancelSpeech, un-commit, merge back into the buffer. After BotAudioStarted the commit is final."
        if new_state.is_committed and not new_state.bot_audio_started:
            effects.append(CancelSpeech())
            if "bridge" in new_state.active_timers:
                effects.append(CancelTimer(name="bridge"))
                new_state.active_timers.pop("bridge", None)
            if "decision_timeout" in new_state.active_timers:
                effects.append(CancelTimer(name="decision_timeout"))
                new_state.active_timers.pop("decision_timeout", None)
            new_state.awaiting_decision = False
            new_state.decision_token = None
            if new_state.phase_before_commit:
                new_state.phase = new_state.phase_before_commit
                new_state.current_question_index = new_state.question_index_before_commit
                new_state.phase_before_commit = None
            new_state.is_committed = False
            new_state.bot_speaking = False
            new_state.active_speech_id = None
            effects.append(EmitUI(status="uncommitted", payload={"answer": new_state.answer_buffer}))

        # Cancel pending commit timer and keep accumulating
        if "commit" in new_state.active_timers:
            effects.append(CancelTimer(name="commit"))
            new_state.active_timers.pop("commit", None)

        # Cancel speculative reply if one was active
        if new_state.active_speculation_token:
            effects.append(CancelSpeculativeReply(token=new_state.active_speculation_token))
            new_state.active_speculation_token = None
            new_state.speculation_source_text = ""

        new_state.is_accumulating = True
        new_state.current_candidate_turn_id = f"turn_{new_state.turn_counter + 1}"
        if new_state.accumulation_started_ms == 0:
            new_state.accumulation_started_ms = event.now_ms

        return new_state, effects

    # 7. EagerTurnEnd
    if isinstance(event, EagerTurnEnd):
        # Only speculate if accumulating and not already committed and bot not speaking
        if new_state.is_accumulating and not new_state.is_committed and not new_state.bot_speaking:
            next_q = get_next_plan_question(new_state)
            next_q_text = next_q.question_text if next_q else ""
            curr_q = _get_current_question(new_state)
            curr_q_text = curr_q.question_text if curr_q else ""
            if next_q_text or curr_q_text:
                new_state.speculation_seq += 1
                token = f"spec_{new_state.speculation_seq}"
                new_state.active_speculation_token = token
                eager_source = f"{new_state.answer_buffer} {event.text}".strip() if new_state.answer_buffer else event.text.strip()
                new_state.speculation_source_text = eager_source

                curr_cand_id = f"turn_{new_state.turn_counter + 1}"
                new_state.current_candidate_turn_id = curr_cand_id
                curr_skill = new_state.skill_names[new_state.current_skill_index] if 0 <= new_state.current_skill_index < len(new_state.skill_names) else ""
                spec_snapshot = DecisionContextSnapshot(
                    session_id=new_state.session_id,
                    candidate_turn_id=curr_cand_id,
                    question_index=new_state.current_question_index,
                    skill_name=curr_skill,
                    phase=new_state.phase.value,
                    normalized_answer=normalize_text_for_hash(eager_source),
                    answer_hash=compute_content_hash(eager_source),
                    question_text=curr_q_text,
                    question_hash=compute_content_hash(curr_q_text),
                    request_id=token,
                    speculation_id=token,
                )
                new_state.active_speculation_snapshot = spec_snapshot
                effects.append(StartSpeculativeReply(
                    token=token,
                    source_text=eager_source,
                    next_question_text=next_q_text,
                    snapshot=spec_snapshot,
                ))
        return new_state, effects

    # 8. TurnResumed
    if isinstance(event, TurnResumed):
        if new_state.active_speculation_token:
            effects.append(CancelSpeculativeReply(token=new_state.active_speculation_token))
            new_state.active_speculation_token = None
            new_state.speculation_source_text = ""
            new_state.active_speculation_snapshot = None
        return new_state, effects

    # 9. TurnEnd (Candidate finished a speech turn hypothesis)
    if isinstance(event, TurnEnd):
        # Duplicate TurnEnd protection by turn_id
        turn_id_str = str(event.turn_id)
        if turn_id_str in new_state.seen_turn_ids:
            return new_state, effects
        new_state.seen_turn_ids.append(turn_id_str)

        # Duplicate TurnEnd protection by equivalent transcript in current accumulation window
        if new_state.answer_buffer and normalize_text_for_hash(event.text) == normalize_text_for_hash(new_state.answer_buffer):
            return new_state, effects

        # In ready gate, candidate speech was already handled in Section 3; do not accumulate into question answer buffer
        if new_state.phase == ConductorPhase.READY_GATE:
            return new_state, effects

        if not new_state.is_committed and (not new_state.current_candidate_turn_id or new_state.current_candidate_turn_id == f"turn_{new_state.turn_counter}"):
            new_state.current_candidate_turn_id = f"turn_{new_state.turn_counter + 1}"

        # Append verbatim text to buffer (no cleanup, no dedupe)
        if not new_state.answer_buffer:
            new_state.answer_buffer = event.text
        else:
            new_state.answer_buffer = f"{new_state.answer_buffer} {event.text}"

        if new_state.accumulation_started_ms == 0:
            new_state.accumulation_started_ms = event.now_ms

        # Completeness check on the accumulated text
        completeness = classify_completeness(new_state.answer_buffer)
        grace_ms = new_state.complete_grace_ms if completeness == Completeness.COMPLETE else new_state.incomplete_grace_ms

        # Cancel any prior commit timer and schedule new one
        if "commit" in new_state.active_timers:
            effects.append(CancelTimer(name="commit"))
            new_state.active_timers.pop("commit", None)

        new_state.timer_seq += 1
        commit_token = f"commit_{new_state.timer_seq}"
        commit_at = event.now_ms + grace_ms
        new_state.active_timers["commit"] = {"at_ms": commit_at, "token": commit_token}
        effects.append(ScheduleTimer(name="commit", at_ms=commit_at, token=commit_token, delay_ms=grace_ms))

        return new_state, effects

    # 10. CommitButton (manual accelerator)
    if isinstance(event, CommitButton):
        if not new_state.is_committed:
            if not new_state.answer_buffer.strip():
                new_state.answer_buffer = "[Skipped by candidate]"
            new_state, commit_effects = _commit_current_turn(new_state, event.now_ms)
            effects.extend(commit_effects)
        return new_state, effects

    # 10b. AckReady (LLM streamed ack string early - Phase A4 Ack-First Streaming)
    if isinstance(event, AckReady):
        if not new_state.awaiting_decision or event.token != new_state.decision_token:
            # Stale or unexpected token ignored
            return new_state, effects

        # Immutable Context Snapshot validation (Phase A6.2 Section 1)
        if event.snapshot and new_state.active_decision_snapshot:
            snap = event.snapshot
            act = new_state.active_decision_snapshot
            if (
                snap.session_id != act.session_id
                or snap.candidate_turn_id != act.candidate_turn_id
                or snap.question_index != act.question_index
                or snap.skill_name != act.skill_name
                or snap.phase != act.phase
                or snap.answer_hash != act.answer_hash
                or snap.question_hash != act.question_hash
            ):
                return new_state, effects

        if new_state.spoken_ack_token == event.token:
            # Already spoken or in flight for this turn
            return new_state, effects

        # Phase A6: Off-topic speaks NO ack
        event_action = getattr(event, "action", "")
        if event_action == "off_topic":
            return new_state, effects

        raw_ack = (event.text or "").strip()
        if not raw_ack:
            return new_state, effects

        curr_q = _get_current_question(new_state)
        curr_q_text = curr_q.question_text if curr_q else ""
        curr_q_id = getattr(curr_q, "id", "") if curr_q else ""
        curr_skill = getattr(curr_q, "skill_name", "") if curr_q else ""
        validated_ack, target_opener = validate_and_format_ack(
            raw_ack=raw_ack,
            last_opener=new_state.last_ack_opener,
            bridge_played=new_state.bridge_played_for_commit,
            turn_counter=new_state.speech_seq,
            candidate_answer=new_state.committed_answer,
            question_text=curr_q_text,
            action=event_action,
            no_experience=getattr(event, "no_experience", False),
            you_mentioned_used_count=new_state.you_mentioned_used_count,
        )

        if validated_ack:
            if "you mentioned" in validated_ack.lower():
                new_state.you_mentioned_used_count += 1

            # Ack starts immediately: cancel any pending bridge timer!
            if "bridge" in new_state.active_timers:
                effects.append(CancelTimer(name="bridge"))
                new_state.active_timers.pop("bridge", None)

            new_state.spoken_ack_token = event.token
            new_state.spoken_ack_text = validated_ack
            new_state.last_ack_opener = target_opener
            new_state.speech_seq += 1
            ack_speech_id = f"ack_speech_{new_state.speech_seq}"
            new_state.active_speech_id = ack_speech_id
            new_state.bot_speaking = True
            new_state.bot_audio_started = False

            effects.append(SpeakAck(
                token=event.token,
                text=validated_ack,
                speech_id=ack_speech_id,
                action=event_action,
                question_id=curr_q_id,
                skill_name=curr_skill,
            ))
            effects.append(EmitUI(status="bot_speaking_ack", payload={"ack": validated_ack, "token": event.token}))

        return new_state, effects

    # 11. DecisionReady (LLM decision response arrived)
    if isinstance(event, DecisionReady):
        if not new_state.awaiting_decision or event.token != new_state.decision_token:
            # Stale decision token ignored
            return new_state, effects

        # Immutable Context Snapshot validation (Phase A6.2 Section 1)
        if event.snapshot and new_state.active_decision_snapshot:
            snap = event.snapshot
            act = new_state.active_decision_snapshot
            if (
                snap.session_id != act.session_id
                or snap.candidate_turn_id != act.candidate_turn_id
                or snap.question_index != act.question_index
                or snap.skill_name != act.skill_name
                or snap.phase != act.phase
                or snap.answer_hash != act.answer_hash
                or snap.question_hash != act.question_hash
            ):
                return new_state, effects

        # Cancel decision_timeout and ack_fallback timers
        if "decision_timeout" in new_state.active_timers:
            effects.append(CancelTimer(name="decision_timeout"))
            new_state.active_timers.pop("decision_timeout", None)
        if "ack_fallback" in new_state.active_timers:
            effects.append(CancelTimer(name="ack_fallback"))
            new_state.active_timers.pop("ack_fallback", None)

        ack_currently_playing = bool(
            new_state.bot_speaking
            and new_state.active_speech_id
            and new_state.active_speech_id.startswith("ack_speech_")
        )
        current_active_speech_id = new_state.active_speech_id

        new_state, dec_effects = validate_and_apply_decision(new_state, event.decision, event.now_ms)

        # If ack speech is currently active, defer speaking question until BotSpeechDone for the ack
        if ack_currently_playing:
            new_state.active_speech_id = current_active_speech_id
            new_state.bot_speaking = True
            new_state.pending_question_effects = dec_effects
        else:
            effects.extend(dec_effects)

        return new_state, effects

        # Cancel decision_timeout and ack_fallback timers
        if "decision_timeout" in new_state.active_timers:
            effects.append(CancelTimer(name="decision_timeout"))
            new_state.active_timers.pop("decision_timeout", None)
        if "ack_fallback" in new_state.active_timers:
            effects.append(CancelTimer(name="ack_fallback"))
            new_state.active_timers.pop("ack_fallback", None)

        ack_currently_playing = bool(
            new_state.bot_speaking
            and new_state.active_speech_id
            and new_state.active_speech_id.startswith("ack_speech_")
        )
        current_active_speech_id = new_state.active_speech_id

        new_state, dec_effects = validate_and_apply_decision(new_state, event.decision, event.now_ms)

        # If ack speech is currently active, defer speaking question until BotSpeechDone for the ack
        if ack_currently_playing:
            new_state.active_speech_id = current_active_speech_id
            new_state.bot_speaking = True
            new_state.pending_question_effects = dec_effects
        else:
            effects.extend(dec_effects)

        return new_state, effects

    # 12. Tick (Timer checks, hard cap, silence progression, bridge playback, decision timeout)
    if isinstance(event, Tick):
        now_ms = event.now_ms

        # A. Check Hard Cap (180s of accumulating force-commits)
        if (
            new_state.is_accumulating
            and not new_state.is_committed
            and new_state.accumulation_started_ms > 0
            and (now_ms - new_state.accumulation_started_ms) >= new_state.hard_cap_ms
            and new_state.answer_buffer.strip()
        ):
            new_state, commit_effects = _commit_current_turn(new_state, now_ms)
            effects.extend(commit_effects)
            return new_state, effects

        # B. Check Commit Timer
        if "commit" in new_state.active_timers:
            timer_info = new_state.active_timers["commit"]
            if now_ms >= timer_info["at_ms"]:
                # Commit fires!
                new_state.active_timers.pop("commit", None)
                if not new_state.is_committed and new_state.answer_buffer.strip():
                    new_state, commit_effects = _commit_current_turn(new_state, now_ms)
                    effects.extend(commit_effects)
                    return new_state, effects

        # C1. Check Ack Fallback Timer (500ms after ack playback finished with no decision)
        if "ack_fallback" in new_state.active_timers:
            timer_info = new_state.active_timers["ack_fallback"]
            if now_ms >= timer_info["at_ms"] and new_state.awaiting_decision:
                new_state.active_timers.pop("ack_fallback", None)
                new_state, fb_effects = validate_and_apply_decision(new_state, None, now_ms)
                effects.extend(fb_effects)
                return new_state, effects

        # C2. Check 4s Hard Cap after commit when awaiting decision
        if new_state.awaiting_decision and new_state.decision_start_ms > 0 and (now_ms - new_state.decision_start_ms) >= 4000:
            if "decision_timeout" in new_state.active_timers:
                effects.append(CancelTimer(name="decision_timeout"))
                new_state.active_timers.pop("decision_timeout", None)
            if "ack_fallback" in new_state.active_timers:
                effects.append(CancelTimer(name="ack_fallback"))
                new_state.active_timers.pop("ack_fallback", None)
            new_state, fb_effects = validate_and_apply_decision(new_state, None, now_ms)
            effects.extend(fb_effects)
            return new_state, effects

        # C3. Check Decision Timeout Timer (1500ms after commit, force deterministic fallback if no ack)
        if "decision_timeout" in new_state.active_timers:
            timer_info = new_state.active_timers["decision_timeout"]
            if (now_ms >= timer_info["at_ms"] or event.token == timer_info.get("token")) and (
                not event.token or event.token == new_state.decision_token
            ):
                new_state.active_timers.pop("decision_timeout", None)
                # If an ack was already spoken or is speaking, wait for ack_fallback or 4s cap instead
                ack_already_active = bool(new_state.spoken_ack_token and new_state.spoken_ack_token == new_state.decision_token)
                if not ack_already_active and new_state.awaiting_decision:
                    new_state, fb_effects = validate_and_apply_decision(new_state, None, now_ms)
                    effects.extend(fb_effects)
                    return new_state, effects

        # Direct token match for stale/targeted Tick
        if event.token and event.token == new_state.decision_token and new_state.awaiting_decision:
            if "decision_timeout" in new_state.active_timers:
                effects.append(CancelTimer(name="decision_timeout"))
                new_state.active_timers.pop("decision_timeout", None)
            new_state, fb_effects = validate_and_apply_decision(new_state, None, now_ms)
            effects.extend(fb_effects)
            return new_state, effects

        # D. Check Bridge Timer (700ms after commit ONLY IF no ack has started!)
        if "bridge" in new_state.active_timers:
            timer_info = new_state.active_timers["bridge"]
            if now_ms >= timer_info["at_ms"]:
                new_state.active_timers.pop("bridge", None)
                ack_already_started = bool(new_state.spoken_ack_token and new_state.spoken_ack_token == new_state.decision_token)
                if not new_state.bot_audio_started and not new_state.bridge_played_for_commit and not ack_already_started:
                    bridge_text, next_bridge_idx = get_next_bridge(new_state.last_bridge_index)
                    new_state.last_bridge_index = next_bridge_idx
                    new_state.bridge_played_for_commit = True
                    new_state.speech_seq += 1
                    bridge_speech_id = f"bridge_{new_state.speech_seq}"
                    effects.append(PlayBridge(text=bridge_text, speech_id=bridge_speech_id))

        # E. Check Silence Progression (25s nudge, 60s repeat, 90s move on)
        if (
            "silence" in new_state.active_timers
            and not new_state.bot_speaking
            and not new_state.is_accumulating
            and new_state.question_active_at_ms > 0
            and new_state.phase not in (ConductorPhase.WELCOME, ConductorPhase.READY_GATE, ConductorPhase.COMPLETED)
        ):
            silence_info = new_state.active_timers["silence"]
            if now_ms >= silence_info["at_ms"]:
                elapsed = now_ms - new_state.question_active_at_ms

                # At 25s: Speak("Take your time. Want me to repeat the question?") once
                if elapsed < 55000 and not new_state.silence_nudge_emitted:
                    new_state.silence_nudge_emitted = True
                    new_state.speech_seq += 1
                    nudge_speech_id = f"nudge_speech_{new_state.speech_seq}"
                    new_state.active_speech_id = nudge_speech_id
                    new_state.bot_speaking = True
                    new_state.bot_audio_started = False
                    effects.append(Speak(text="Take your time. Want me to repeat the question?", speech_id=nudge_speech_id))

                    # Reschedule for 60s
                    new_state.timer_seq += 1
                    token = f"silence_{new_state.timer_seq}"
                    new_state.active_timers["silence"] = {"at_ms": new_state.question_active_at_ms + 60000, "token": token}
                    effects.append(ScheduleTimer(name="silence", at_ms=new_state.question_active_at_ms + 60000, token=token, delay_ms=35000))
                    return new_state, effects

                # At 60s: Repeat the question once
                elif elapsed < 85000 and not new_state.silence_repeat_emitted:
                    new_state.silence_repeat_emitted = True
                    curr_q = _get_current_question(new_state)
                    q_text = curr_q.question_text if curr_q else "Please take your time to answer."
                    new_state.speech_seq += 1
                    repeat_speech_id = f"silence_repeat_speech_{new_state.speech_seq}"
                    new_state.active_speech_id = repeat_speech_id
                    new_state.bot_speaking = True
                    new_state.bot_audio_started = False
                    effects.append(Speak(text=q_text, speech_id=repeat_speech_id))

                    # Reschedule for 90s
                    new_state.timer_seq += 1
                    token = f"silence_{new_state.timer_seq}"
                    new_state.active_timers["silence"] = {"at_ms": new_state.question_active_at_ms + 90000, "token": token}
                    effects.append(ScheduleTimer(name="silence", at_ms=new_state.question_active_at_ms + 90000, token=token, delay_ms=30000))
                    return new_state, effects

                # At 90s: Mark unanswered and move on
                elif elapsed >= 85000:
                    new_state.active_timers.pop("silence", None)
                    curr_q = _get_current_question(new_state)
                    turn_data = {
                        "question_index": curr_q.question_index if curr_q else 0,
                        "question_text": curr_q.question_text if curr_q else "",
                        "skill_name": curr_q.skill_name if curr_q else "",
                        "answer": "[Unanswered / 90s Silence Timeout]",
                        "unanswered": True,
                    }
                    effects.append(Persist(turn=turn_data))
                    new_state, adv_effects = _advance_script_after_turn(new_state, answer_text="[Unanswered]", is_short=True, now_ms=now_ms)
                    effects.extend(adv_effects)
                    return new_state, effects

        return new_state, effects

    return new_state, effects


# -----------------------------------------------------------------------------
# Script Progression & Commit Helpers
# -----------------------------------------------------------------------------

def _get_current_question(state: ConductorState) -> Optional[PlanQuestion]:
    for q in state.questions:
        if q.question_index == state.current_question_index:
            return q
    return None


def _commit_current_turn(state: ConductorState, now_ms: int) -> Tuple[ConductorState, List[ConductorEffect]]:
    """Commit the accumulated answer buffer, persist turn, and advance to next question."""
    effects: List[ConductorEffect] = []
    curr_q = _get_current_question(state)

    state.phase_before_commit = state.phase
    state.question_index_before_commit = state.current_question_index
    state.is_committed = True
    state.committed_answer = state.answer_buffer
    state.is_accumulating = False
    state.accumulation_started_ms = 0
    state.turn_counter += 1
    state.current_candidate_turn_id = f"turn_{state.turn_counter}"

    # Cancel commit and silence timers
    if "commit" in state.active_timers:
        effects.append(CancelTimer(name="commit"))
        state.active_timers.pop("commit", None)
    if "silence" in state.active_timers:
        effects.append(CancelTimer(name="silence"))
        state.active_timers.pop("silence", None)

    # Persist the completed turn
    turn_record = {
        "turn_index": state.turn_counter,
        "question_index": curr_q.question_index if curr_q else 0,
        "question_kind": curr_q.kind if curr_q else "",
        "question_text": curr_q.question_text if curr_q else "",
        "skill_name": curr_q.skill_name if curr_q else "",
        "answer": state.committed_answer,
        "word_count": count_words(state.committed_answer),
    }
    effects.append(Persist(turn=turn_record))

    # Schedule conversational bridge timer after commit (default 700ms)
    state.bridge_played_for_commit = False
    state.spoken_ack_token = None
    state.spoken_ack_text = ""
    state.pending_question_effects = []
    state.ack_playback_ended_at_ms = None
    state.commit_at_ms = now_ms
    state.timer_seq += 1
    bridge_token = f"bridge_{state.timer_seq}"
    b_delay = getattr(state, "bridge_delay_ms", 700) or 700
    state.active_timers["bridge"] = {"at_ms": now_ms + b_delay, "token": bridge_token}
    effects.append(ScheduleTimer(name="bridge", at_ms=now_ms + b_delay, token=bridge_token, delay_ms=b_delay))

    # Conductor Phase A: In SKILL_ANCHOR or SKILL_FOLLOWUP, emit RequestDecision and enter AWAIT_DECISION sub-state
    if state.phase in (ConductorPhase.SKILL_ANCHOR, ConductorPhase.SKILL_FOLLOWUP) and 0 <= state.current_skill_index < len(state.skill_names):
        curr_skill = state.skill_names[state.current_skill_index]
        sq = state.skill_questions.get(curr_skill, {})

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
        expectations = list(curr_q.expected_key_points) if curr_q else []
        stretch_expectations = list(getattr(curr_q, "stretch_key_points", [])) if curr_q else []
        followups_used = state.followups_used_per_skill.get(curr_skill, 0)
        time_left_ms = get_skill_time_left_ms(state, curr_skill, now_ms)

        state.decision_seq += 1
        dec_token = f"decision_{state.decision_seq}"
        state.awaiting_decision = True
        state.decision_token = dec_token
        state.decision_start_ms = now_ms

        # Immutable Context Snapshot (Phase A6 Section 3)
        curr_cand_id = state.current_candidate_turn_id
        norm_ans = normalize_text_for_hash(state.committed_answer)
        ans_hash = compute_content_hash(state.committed_answer)
        curr_q_text = curr_q.question_text if curr_q else ""
        q_hash = compute_content_hash(curr_q_text)

        snapshot = DecisionContextSnapshot(
            session_id=state.session_id,
            candidate_turn_id=curr_cand_id,
            question_index=state.current_question_index,
            skill_name=curr_skill,
            phase=state.phase.value,
            normalized_answer=norm_ans,
            answer_hash=ans_hash,
            question_text=curr_q_text,
            question_hash=q_hash,
            request_id=dec_token,
        )
        state.active_decision_snapshot = snapshot

        # Decision timeout timer
        timeout_ms = state.decision_timeout_ms
        state.active_timers["decision_timeout"] = {"at_ms": now_ms + timeout_ms, "token": dec_token}
        effects.append(ScheduleTimer(name="decision_timeout", at_ms=now_ms + timeout_ms, token=dec_token, delay_ms=timeout_ms))

        effects.append(RequestDecision(
            token=dec_token,
            skill=curr_skill,
            question_text=curr_q.question_text if curr_q else "",
            answer_text=state.committed_answer,
            probes=probes_list,
            escalation_text=escalation_text,
            anchor_alt_text=anchor_alt_text,
            expectations=expectations,
            stretch_expectations=stretch_expectations,
            followups_used=followups_used,
            time_left_ms=time_left_ms,
            last_ack_opener=state.last_ack_opener,
            snapshot=snapshot,
        ))
        effects.append(EmitUI(status="awaiting_decision", payload={"skill": curr_skill, "token": dec_token}))
        return state, effects

    # Candidate Q&A multi-round handling (Requirement 3 & 4)
    if state.phase == ConductorPhase.CANDIDATE_QA:
        # If no job_record, candidate says no/done, or max 3 rounds reached: advance to CLOSING
        if not state.job_record or is_qa_done_phrase(state.committed_answer) or state.qa_rounds_used >= 3:
            closing_q = next((q for q in state.questions if q.kind == "closing"), None)
            closing_text = (
                closing_q.question_text
                if closing_q and closing_q.question_text
                else "Thank you so much for taking the time to speak with me today. Have a wonderful rest of your day!"
            )
            state.phase = ConductorPhase.CLOSING
            state.current_question_index = closing_q.question_index if closing_q else 999
            state.asked_questions_history.append(closing_text)
            state.speech_seq += 1
            speech_id = f"speech_{state.speech_seq}"
            state.active_speech_id = speech_id
            state.bot_speaking = True
            state.bot_audio_started = False
            effects.append(Speak(text=closing_text, speech_id=speech_id, ack_text="", question_text=closing_text, kind="closing", question_id="closing"))
            effects.append(EmitUI(status="closing", payload={"question_text": closing_text}))
            return state, effects

        # Candidate asked a question and we have job_record: request answer grounded in job record
        state.qa_rounds_used += 1
        state.decision_seq += 1
        dec_token = f"decision_{state.decision_seq}"
        state.awaiting_decision = True
        state.decision_token = dec_token
        state.decision_start_ms = now_ms

        curr_cand_id = state.current_candidate_turn_id or f"turn_{state.turn_counter}"
        norm_ans = normalize_text_for_hash(state.committed_answer)
        ans_hash = compute_content_hash(state.committed_answer)
        curr_q_text = curr_q.question_text if curr_q else ""
        q_hash = compute_content_hash(curr_q_text)

        snapshot = DecisionContextSnapshot(
            session_id=state.session_id,
            candidate_turn_id=curr_cand_id,
            question_index=state.current_question_index,
            skill_name="Candidate Q&A",
            phase=state.phase.value,
            normalized_answer=norm_ans,
            answer_hash=ans_hash,
            question_text=curr_q_text,
            question_hash=q_hash,
            request_id=dec_token,
        )
        state.active_decision_snapshot = snapshot

        timeout_ms = state.decision_timeout_ms
        state.active_timers["decision_timeout"] = {"at_ms": now_ms + timeout_ms, "token": dec_token}
        effects.append(ScheduleTimer(name="decision_timeout", at_ms=now_ms + timeout_ms, token=dec_token, delay_ms=timeout_ms))
        effects.append(RequestDecision(
            token=dec_token,
            skill="Candidate Q&A",
            question_text=curr_q.question_text if curr_q else "",
            answer_text=state.committed_answer,
            probes=[],
            escalation_text="",
            anchor_alt_text="",
            expectations=[],
            stretch_expectations=[],
            followups_used=state.qa_rounds_used,
            time_left_ms=180000,
            last_ack_opener=state.last_ack_opener,
            snapshot=snapshot,
        ))
        effects.append(EmitUI(status="awaiting_decision", payload={"skill": "Candidate Q&A", "token": dec_token}))
        return state, effects

    # Advance script based on current phase (Intro -> first skill anchor, or QA -> closing)
    is_short = count_words(state.committed_answer) < 6
    state, adv_effects = _advance_script_after_turn(state, answer_text=state.committed_answer, is_short=is_short, now_ms=now_ms)
    effects.extend(adv_effects)
    return state, effects


def validate_and_apply_decision(
    state: ConductorState,
    decision: Optional[Dict[str, Any]],
    now_ms: int,
) -> Tuple[ConductorState, List[ConductorEffect]]:
    """Validate decision JSON against Conductor rules or execute pure deterministic fallback."""
    effects: List[ConductorEffect] = []
    curr_skill = state.skill_names[state.current_skill_index] if 0 <= state.current_skill_index < len(state.skill_names) else ""
    sq = state.skill_questions.get(curr_skill, {})
    curr_q = _get_current_question(state)
    answer = state.committed_answer
    time_left = get_skill_time_left_ms(state, curr_skill, now_ms)
    followups_used = state.followups_used_per_skill.get(curr_skill, 0)
    core_expectations = curr_q.expected_key_points if curr_q else []

    is_valid = False
    action: Optional[str] = None
    ack: str = ""
    followup: str = ""
    probe_id: Optional[str] = None
    no_experience: bool = False
    covered_exps: List[str] = []
    chosen_q: Optional[PlanQuestion] = None

    if isinstance(decision, dict):
        raw_action = str(decision.get("action", "") or "").strip().lower()
        raw_ack = str(decision.get("ack", "") or "").strip()
        raw_followup = str(decision.get("followup", "") or "").strip()
        probe_id = decision.get("probe_id")
        no_experience = bool(decision.get("no_experience", False))
        covered_exps = list(decision.get("covered_expectations", []) or [])

        if raw_action in ("probe", "escalate", "hypothetical", "clarify", "off_topic", "rephrase", "next", "qa_reply"):
            action = raw_action
            ack = raw_ack
            followup = raw_followup
            is_valid = True

    # Candidate Q&A answer handling (Requirement 1 & 4)
    if state.phase == ConductorPhase.CANDIDATE_QA or action == "qa_reply":
        if is_valid and followup:
            ans_text = followup.strip()
            if not ans_text.endswith("?") and state.qa_rounds_used < 3:
                ans_text = f"{ans_text} Anything else?"
        else:
            ans_text = APPROVED_QA_DEFERRAL

        # If answer is approved deferral, suppress ack (Requirement 6)
        if ans_text.startswith(APPROVED_QA_DEFERRAL) or "hiring team will follow up" in ans_text:
            spoken_ack = ""
            recorded_ack = ""
        else:
            ack_already_spoken = bool(state.spoken_ack_token and state.spoken_ack_token == state.decision_token)
            if ack_already_spoken:
                spoken_ack = ""
                recorded_ack = state.spoken_ack_text
            else:
                formatted_ack, target_opener = validate_and_format_ack(
                    raw_ack=ack,
                    last_opener=state.last_ack_opener,
                    bridge_played=state.bridge_played_for_commit,
                    turn_counter=state.speech_seq,
                    candidate_answer=state.committed_answer,
                )
                state.last_ack_opener = target_opener
                spoken_ack = formatted_ack
                recorded_ack = formatted_ack

        full_text = f"{spoken_ack} {ans_text}".strip() if spoken_ack else ans_text
        state.asked_questions_history.append(ans_text)
        state.speech_seq += 1
        speech_id = f"speech_{state.speech_seq}"
        state.active_speech_id = speech_id
        state.bot_speaking = True
        state.bot_audio_started = False

        effects.append(Speak(text=full_text, speech_id=speech_id, ack_text=recorded_ack, question_text=ans_text))
        effects.append(EmitUI(status="candidate_qa", payload={"answer": full_text, "round": state.qa_rounds_used}))

        state.awaiting_decision = False
        state.decision_token = None
        state.decision_start_ms = 0
        return state, effects

    # Rule 1: No experience (Requirement 6: one hypothetical per skill; if second -> warm transition and advance)
    neutral_transition: str = ""
    if is_valid and (no_experience or action == "hypothetical"):
        if state.hypothetical_used_per_skill.get(curr_skill, False):
            action = "next"
            followup = ""
            neutral_transition = "No problem, let's move on."
        else:
            action = "hypothetical"
            state.hypothetical_used_per_skill[curr_skill] = True
            anchor_alt_q = sq.get("anchor_alt")
            if anchor_alt_q:
                chosen_q = anchor_alt_q
                followup = anchor_alt_q.question_text
            elif sq.get("escalation"):
                chosen_q = sq.get("escalation")
                followup = chosen_q.question_text

    # Rule 1b: Clarify action (Requirement 2: max once per skill, grounded in candidate words)
    if is_valid and action == "clarify":
        if state.clarify_used_per_skill.get(curr_skill, False):
            # Max once per skill!
            action = "next"
            followup = ""
        else:
            state.clarify_used_per_skill[curr_skill] = True

    # Rule 1c: Rephrase action (Requirement 5: does not count as follow-up, answer stays attributed to same question)
    if is_valid and action == "rephrase":
        rephrased_text = followup or (curr_q.question_text if curr_q else "")
        ack_already_spoken = bool(state.spoken_ack_token and state.spoken_ack_token == state.decision_token)
        if ack_already_spoken:
            spoken_ack = ""
            recorded_ack = state.spoken_ack_text
        else:
            formatted_ack, target_opener = validate_and_format_ack(
                raw_ack=ack or "Sure, let me rephrase that.",
                last_opener=state.last_ack_opener,
                bridge_played=state.bridge_played_for_commit,
                turn_counter=state.speech_seq,
            )
            state.last_ack_opener = target_opener
            spoken_ack = formatted_ack
            recorded_ack = formatted_ack

        full_text = f"{spoken_ack} {rephrased_text}".strip() if spoken_ack else rephrased_text
        state.speech_seq += 1
        speech_id = f"speech_{state.speech_seq}"
        state.active_speech_id = speech_id
        state.bot_speaking = True
        state.bot_audio_started = False

        effects.append(Speak(text=full_text, speech_id=speech_id, ack_text=recorded_ack, question_text=rephrased_text))
        effects.append(EmitUI(status="rephrasing_question", payload={"question_text": rephrased_text, "ack": recorded_ack}))

        state.awaiting_decision = False
        state.decision_token = None
        state.decision_start_ms = 0
        return state, effects

    # Rule 1d: Off-topic action (Requirement 6: simpler rewording sharing >=3 content words, prefixed with "Let's come back to it. ")
    off_topic_move_on: bool = False
    if is_valid and action == "off_topic":
        # Phase A6: Speak NO acknowledgment about unrelated candidate content
        ans_content = {w for w in re.findall(r"\b[a-zA-Z]{3,}\b", answer.lower()) if w not in STOPWORDS}
        ack_content = {w for w in re.findall(r"\b[a-zA-Z]{3,}\b", ack.lower()) if w not in STOPWORDS}
        if ans_content.intersection(ack_content) or any(w in ack.lower() for w in ("coffee", "espresso", "parking", "lunch", "weather", "permit")):
            ack = ""
        retries = state.off_topic_retries_per_question.get(state.current_question_index, 0)
        curr_off_count = state.off_topic_count_per_skill.get(curr_skill, 0) + 1
        state.off_topic_count_per_skill[curr_skill] = curr_off_count

        if curr_off_count >= 2:
            state.insufficient_evidence_per_skill[curr_skill] = True
            action = "next"
            followup = ""
            off_topic_move_on = True
        elif retries == 0:
            state.off_topic_retries_per_question[state.current_question_index] = 1
            curr_text = curr_q.question_text if curr_q else ""
            orig_words = [w for w in re.findall(r"\b[a-zA-Z]{3,}\b", curr_text.lower()) if w not in STOPWORDS]

            is_meta = bool(re.search(
                r"\b(are you ready to answer|could you address the question about|can you answer the question about|please answer the question)\b",
                followup or "",
                re.IGNORECASE,
            ))
            fol_words = set(w for w in re.findall(r"\b[a-zA-Z]{3,}\b", (followup or "").lower()) if w not in STOPWORDS)
            word_overlap = len(set(orig_words).intersection(fol_words))

            if is_meta or word_overlap < 3 or not followup:
                overlap_sample = orig_words[:3] if len(orig_words) >= 3 else orig_words
                kw_str = " ".join(overlap_sample)
                followup = f"Could you explain your experience with {kw_str}?"

            if not followup.lower().startswith("let's come back to it"):
                followup = f"Let's come back to it. {followup}"
        else:
            action = "next"
            followup = ""
            off_topic_move_on = True

    # Rule 2: Expectations & progression (Requirement 5)
    stretch_expectations = list(getattr(curr_q, "stretch_key_points", [])) if curr_q else []
    if is_valid and action not in ("off_topic", "rephrase"):
        curr_covered = set(state.covered_expectations_per_skill.get(curr_skill, []))
        for exp in covered_exps:
            curr_covered.add(exp.strip().lower())
        state.covered_expectations_per_skill[curr_skill] = list(curr_covered)

        all_core_covered = False
        if core_expectations:
            all_core_covered = all(
                any(ce.strip().lower() in cov for cov in curr_covered)
                for ce in core_expectations
            )

        all_stretch_covered = True
        if stretch_expectations:
            all_stretch_covered = all(
                any(se.strip().lower() in cov for cov in curr_covered)
                for se in stretch_expectations
            )

        should_escalate_stretch = (
            all_core_covered
            and not all_stretch_covered
            and time_left > 120000
            and followups_used < 2
            and not state.escalation_used_for_skill.get(curr_skill, False)
        )

        if should_escalate_stretch:
            action = "escalate"
            esc_q = sq.get("escalation")
            if esc_q:
                chosen_q = esc_q
                followup = esc_q.question_text
            state.escalation_used_for_skill[curr_skill] = True

        elif followups_used >= 2 or time_left < 60000 or (all_core_covered and all_stretch_covered) or (all_core_covered and not stretch_expectations):
            action = "next"
            followup = ""

    # Rule 3: Never repeat a question already asked (>60% token overlap) - excludes off_topic and rephrase
    if is_valid and action in ("probe", "escalate", "hypothetical", "clarify") and followup:
        for prior_q in state.asked_questions_history:
            if check_token_overlap(followup, prior_q) > 0.60 or check_token_overlap(prior_q, followup) > 0.60:
                is_valid = False
                break

    # Rule 4: Followup must be exactly one question, <= 28 words, and match blueprint probe/escalation/hypothetical or reuse candidate content
    if is_valid and action in ("probe", "escalate", "hypothetical", "clarify", "off_topic") and followup:
        if followup.count("?") != 1:
            is_valid = False
        elif count_words(followup) > 28:
            is_valid = False
        else:
            matches_blueprint = False
            blueprint_candidates = []
            if sq.get("anchor_alt"):
                blueprint_candidates.append(sq["anchor_alt"])
            if sq.get("escalation"):
                blueprint_candidates.append(sq["escalation"])
            for p in sq.get("probes", []):
                blueprint_candidates.append(p)
                if probe_id and str(p.probe_id or p.question_index) == str(probe_id):
                    matches_blueprint = True
                    chosen_q = p

            for bp_q in blueprint_candidates:
                if normalize_text(bp_q.question_text) == normalize_text(followup):
                    matches_blueprint = True
                    chosen_q = bp_q
                    break

            reuses_candidate_content = False
            ans_content_words = [
                w for w in re.findall(r"\b[a-zA-Z]{3,}\b", answer.lower())
                if w not in STOPWORDS
            ]
            if ans_content_words:
                f_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", followup.lower()))
                overlap_words = f_words.intersection(ans_content_words)
                if len(overlap_words) >= 1 or any(w in f_words for w in ans_content_words if len(w) >= 4) or action in ("clarify", "off_topic"):
                    reuses_candidate_content = True
            elif action in ("clarify", "off_topic"):
                reuses_candidate_content = True

            if not (matches_blueprint or reuses_candidate_content):
                is_valid = False

    # Rule 5: ack validation (Requirement 4: Ack Validator & A5 Ack Grounding)
    if is_valid and ack:
        curr_q = _get_current_question(state)
        curr_q_text = curr_q.question_text if curr_q else ""
        validated_ack, target_opener = validate_and_format_ack(
            raw_ack=ack,
            last_opener=state.last_ack_opener,
            bridge_played=state.bridge_played_for_commit,
            turn_counter=state.speech_seq,
            candidate_answer=state.committed_answer,
            question_text=curr_q_text,
        )
        if validated_ack:
            ack = validated_ack
            state.last_ack_opener = target_opener
        else:
            ack = ""
    elif is_valid and not ack:
        ack = ""

    # Pure Conductor Deterministic Fallback (Requirements 2 & 4)
    if not is_valid:
        ack = "Understood."
        best_probe = None
        max_overlap = 0
        ans_lower = answer.lower()

        for p in sq.get("probes", []):
            if p.question_text in state.asked_questions_history:
                continue
            tc = p.trigger_condition or ""
            tc_words = [w for w in re.findall(r"\b[a-zA-Z]{3,}\b", tc.lower()) if w not in STOPWORDS]
            overlap = sum(1 for w in tc_words if re.search(r"\b" + re.escape(w) + r"\b", ans_lower))
            if overlap > max_overlap:
                max_overlap = overlap
                best_probe = p

        if max_overlap >= 2 and best_probe and followups_used < 2 and time_left >= 60000:
            action = "probe"
            chosen_q = best_probe
            followup = best_probe.question_text
        elif (
            count_words(answer) < 15
            and not state.clarify_used_per_skill.get(curr_skill, False)
            and followups_used < 2
            and time_left >= 60000
        ):
            # Vague or short answer (< 15 words) with no probe match: one templated clarify question per skill, never escalation!
            action = "clarify"
            followup = "Could you share a concrete example from your work demonstrating that?"
            state.clarify_used_per_skill[curr_skill] = True
        else:
            action = "next"
            followup = ""

    # Execute Chosen Action & Compute Deterministic Transitions (Requirement 5)
    next_q: Optional[PlanQuestion] = None
    transition_prefix: str = ""

    if action == "off_topic" and state.off_topic_retries_per_question.get(state.current_question_index, 0) == 1:
        # Off-topic first retry: stay on same question and same skill!
        next_q = curr_q
        question_text = followup or (curr_q.question_text if curr_q else "Could you share your thoughts on the question?")

    elif action == "next":
        next_skill_idx = state.current_skill_index + 1
        if next_skill_idx < len(state.skill_names):
            state.current_skill_index = next_skill_idx
            next_skill = state.skill_names[next_skill_idx]
            anchor_q = state.skill_questions.get(next_skill, {}).get("anchor") or _find_next_skill_question(state, next_skill_idx)
            if anchor_q:
                state.phase = ConductorPhase.SKILL_ANCHOR
                state.current_question_index = anchor_q.question_index
                state.current_skill_start_ms = now_ms
                next_q = anchor_q
            transition_prefix = f"Let's move on to {next_skill}."
        else:
            # All skills finished -> Candidate Q&A
            qa_q = next((q for q in state.questions if q.kind == "candidate_qa"), None)
            state.phase = ConductorPhase.CANDIDATE_QA
            state.current_question_index = qa_q.question_index if qa_q else 888
            next_q = qa_q

        question_text = next_q.question_text if next_q else (followup or "Thank you. Let's move to the next topic.")
        if off_topic_move_on:
            transition_prefix = "No problem, let's move on to the next topic."
        elif neutral_transition:
            transition_prefix = neutral_transition

    else:
        # action in ("probe", "escalate", "hypothetical", "clarify")
        state.phase = ConductorPhase.SKILL_FOLLOWUP
        state.followups_used_per_skill[curr_skill] = followups_used + 1

        if action == "escalate":
            # Escalation transition rule: if escalation text has <2 content words in common with answer -> "Let me take that a bit further."
            ans_words = set(w for w in re.findall(r"\b[a-zA-Z]{3,}\b", answer.lower()) if w not in STOPWORDS)
            esc_words = set(w for w in re.findall(r"\b[a-zA-Z]{3,}\b", (followup or "").lower()) if w not in STOPWORDS)
            if len(ans_words.intersection(esc_words)) < 2:
                transition_prefix = "Let me take that a bit further."

        if chosen_q is not None:
            next_q = chosen_q
            state.current_question_index = chosen_q.question_index
        else:
            # Check if followup exists in plan
            existing = next((q for q in state.questions if normalize_text(q.question_text) == normalize_text(followup)), None)
            if existing:
                next_q = existing
                state.current_question_index = existing.question_index
            else:
                # Dynamic follow-up (Requirement 8)
                state.dynamic_question_seq += 1
                dyn_idx = 1000 + state.dynamic_question_seq
                next_q = PlanQuestion(
                    question_index=dyn_idx,
                    kind="followup_dynamic",
                    skill_name=curr_skill,
                    question_text=followup,
                )
                state.questions.append(next_q)
                state.current_question_index = dyn_idx

        question_text = next_q.question_text if next_q else (followup or "Thank you. Let's move to the next topic.")

    # Ack handling: if ack was already spoken by AckReady, do NOT speak it again!
    ack_already_spoken = bool(state.spoken_ack_token and state.spoken_ack_token == state.decision_token)
    if ack_already_spoken:
        spoken_ack = ""
        recorded_ack = state.spoken_ack_text
    else:
        spoken_ack = ack
        recorded_ack = ack

    # Spoken order: ack, transition, question
    spoken_parts = []
    if spoken_ack:
        spoken_parts.append(spoken_ack)
    if transition_prefix:
        spoken_parts.append(transition_prefix)
    if question_text:
        spoken_parts.append(question_text)
    full_spoken_text = " ".join(spoken_parts).strip()

    # Record in asked questions history (record transition + question)
    full_recorded_q = f"{transition_prefix} {question_text}".strip() if transition_prefix else question_text
    state.asked_questions_history.append(full_recorded_q)

    # Emit speech
    state.speech_seq += 1
    speech_id = f"speech_{state.speech_seq}"
    state.active_speech_id = speech_id
    state.bot_speaking = True
    state.bot_audio_started = False

    effects.append(Speak(text=full_spoken_text, speech_id=speech_id, ack_text=recorded_ack, question_text=full_recorded_q))
    effects.append(EmitUI(status=state.phase.value, payload={"skill": curr_skill, "question_text": full_recorded_q, "ack": recorded_ack, "action": action, "transition": transition_prefix}))

    # Reset decision sub-state
    state.awaiting_decision = False
    state.decision_token = None
    state.decision_start_ms = 0

    return state, effects


def _advance_script_after_turn(
    state: ConductorState,
    answer_text: str,
    is_short: bool,
    now_ms: int,
) -> Tuple[ConductorState, List[ConductorEffect]]:
    """Determine and speak the next question according to blueprint pacing and rules."""
    effects: List[ConductorEffect] = []

    # 1. INTRO -> first skill's ANCHOR
    if state.phase == ConductorPhase.INTRO:
        if state.skill_names:
            state.current_skill_index = 0
            curr_skill = state.skill_names[0]
            anchor_q = state.skill_questions.get(curr_skill, {}).get("anchor")
            next_q = anchor_q or _find_next_skill_question(state, 0)
            if next_q:
                state.phase = ConductorPhase.SKILL_ANCHOR
                state.current_question_index = next_q.question_index
                state.current_skill_start_ms = now_ms
                ack = generate_intro_ack(answer_text) if answer_text else ""
                if ack:
                    state.last_ack_opener = "Right,"
                if state.bridge_played_for_commit:
                    ack = ""
                full_text = f"{ack} {next_q.question_text}".strip() if ack else next_q.question_text
                state.asked_questions_history.append(next_q.question_text)
                state.speech_seq += 1
                speech_id = f"speech_{state.speech_seq}"
                state.active_speech_id = speech_id
                state.bot_speaking = True
                state.bot_audio_started = False
                effects.append(Speak(text=full_text, speech_id=speech_id, ack_text=ack, question_text=next_q.question_text))
                effects.append(EmitUI(status="skill_anchor", payload={"skill": curr_skill, "question_text": next_q.question_text, "ack": ack}))
                return state, effects

        # No skills -> Candidate Q&A
        return _transition_to_qa(state)

    # 2. CANDIDATE_QA -> CLOSING
    if state.phase == ConductorPhase.CANDIDATE_QA:
        closing_q = next((q for q in state.questions if q.kind == "closing"), None)
        closing_text = (
            closing_q.question_text
            if closing_q
            else "Thank you so much for taking the time to speak with me today. Have a wonderful rest of your day!"
        )
        state.phase = ConductorPhase.CLOSING
        state.current_question_index = closing_q.question_index if closing_q else 999
        state.asked_questions_history.append(closing_text)
        state.speech_seq += 1
        speech_id = f"speech_{state.speech_seq}"
        state.active_speech_id = speech_id
        state.bot_speaking = True
        state.bot_audio_started = False
        effects.append(Speak(text=closing_text, speech_id=speech_id, question_text=closing_text))
        effects.append(EmitUI(status="closing", payload={"question_text": closing_text}))
        return state, effects

    return state, effects


def _advance_to_next_skill(state: ConductorState) -> Tuple[ConductorState, List[ConductorEffect]]:
    """Advance to the next skill in the plan, or transition to Candidate Q&A if done."""
    effects: List[ConductorEffect] = []
    next_skill_idx = state.current_skill_index + 1

    if next_skill_idx < len(state.skill_names):
        state.current_skill_index = next_skill_idx
        next_skill = state.skill_names[next_skill_idx]
        anchor_q = state.skill_questions.get(next_skill, {}).get("anchor")
        if not anchor_q:
            anchor_q = _find_next_skill_question(state, next_skill_idx)

        if anchor_q:
            state.phase = ConductorPhase.SKILL_ANCHOR
            state.current_question_index = anchor_q.question_index
            state.speech_seq += 1
            speech_id = f"speech_{state.speech_seq}"
            state.active_speech_id = speech_id
            state.bot_speaking = True
            state.bot_audio_started = False
            effects.append(Speak(text=anchor_q.question_text, speech_id=speech_id))
            effects.append(EmitUI(status="skill_anchor", payload={"skill": next_skill, "question_text": anchor_q.question_text}))
            return state, effects

    # All skills finished -> Candidate Q&A
    return _transition_to_qa(state)


def _transition_to_qa(state: ConductorState) -> Tuple[ConductorState, List[ConductorEffect]]:
    """Transition to candidate Q&A."""
    effects: List[ConductorEffect] = []
    qa_q = next((q for q in state.questions if q.kind == "candidate_qa"), None)
    qa_text = (
        qa_q.question_text
        if qa_q
        else "Now I would love to open up the floor to you. What questions do you have for us regarding the team or role?"
    )
    state.phase = ConductorPhase.CANDIDATE_QA
    state.current_question_index = qa_q.question_index if qa_q else 888
    state.speech_seq += 1
    speech_id = f"speech_{state.speech_seq}"
    state.active_speech_id = speech_id
    state.bot_speaking = True
    state.bot_audio_started = False
    effects.append(Speak(text=qa_text, speech_id=speech_id))
    effects.append(EmitUI(status="candidate_qa", payload={"question_text": qa_text}))
    return state, effects


def _find_next_skill_question(state: ConductorState, skill_idx: int) -> Optional[PlanQuestion]:
    if skill_idx < len(state.skill_names):
        s_name = state.skill_names[skill_idx]
        sq = state.skill_questions.get(s_name, {})
        return sq.get("anchor") or sq.get("anchor_alt") or sq.get("escalation")
    return None
