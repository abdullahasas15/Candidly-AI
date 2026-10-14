import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SessionState(str, Enum):
    SCHEDULED = "scheduled"
    PREFLIGHT = "preflight"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InterviewPhase(str, Enum):
    GREETING = "greeting"
    READY_CHECK = "ready_check"
    SELF_INTRO = "self_intro"
    DEEP_DIVE = "deep_dive"
    CANDIDATE_QUESTIONS = "candidate_questions"
    CLOSING = "closing"
    COMPLETED = "completed"


class QuestionState(str, Enum):
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    ASKED = "asked"
    IN_PROGRESS = "in_progress"
    CANDIDATE_TURN = "candidate_turn"
    EVALUATING = "evaluating"
    FOLLOW_UP = "follow_up"
    ANSWERED = "answered"
    SKIPPED = "skipped"
    COMPLETED = "completed"


class TurnType(str, Enum):
    GREETING = "greeting"
    READY_CHECK = "ready_check"
    SELF_INTRO_PROMPT = "self_intro_prompt"
    MAIN_QUESTION = "main_question"
    FOLLOW_UP = "follow_up"
    CLARIFICATION = "clarification"
    SILENCE_NUDGE = "silence_nudge"
    CANDIDATE_ANSWER = "candidate_answer"
    CANDIDATE_QUESTION = "candidate_question"
    CLOSING = "closing"


SESSION_TRANSITIONS = {
    SessionState.SCHEDULED: {SessionState.PREFLIGHT, SessionState.IN_PROGRESS, SessionState.CANCELLED},
    SessionState.PREFLIGHT: {SessionState.IN_PROGRESS, SessionState.CANCELLED},
    SessionState.IN_PROGRESS: {SessionState.PAUSED, SessionState.COMPLETED, SessionState.CANCELLED},
    SessionState.PAUSED: {SessionState.IN_PROGRESS, SessionState.COMPLETED, SessionState.CANCELLED},
    SessionState.COMPLETED: set(),
    SessionState.CANCELLED: set(),
}

PHASE_TRANSITIONS = {
    InterviewPhase.GREETING: {InterviewPhase.READY_CHECK, InterviewPhase.SELF_INTRO},
    InterviewPhase.READY_CHECK: {InterviewPhase.SELF_INTRO, InterviewPhase.DEEP_DIVE},
    InterviewPhase.SELF_INTRO: {InterviewPhase.DEEP_DIVE},
    InterviewPhase.DEEP_DIVE: {InterviewPhase.CANDIDATE_QUESTIONS, InterviewPhase.CLOSING},
    InterviewPhase.CANDIDATE_QUESTIONS: {InterviewPhase.CLOSING, InterviewPhase.COMPLETED},
    InterviewPhase.CLOSING: {InterviewPhase.COMPLETED},
    InterviewPhase.COMPLETED: set(),
}

QUESTION_TRANSITIONS = {
    QuestionState.NOT_STARTED: {QuestionState.QUEUED, QuestionState.ASKED, QuestionState.IN_PROGRESS, QuestionState.SKIPPED},
    QuestionState.QUEUED: {QuestionState.ASKED, QuestionState.IN_PROGRESS, QuestionState.SKIPPED},
    QuestionState.ASKED: {QuestionState.CANDIDATE_TURN, QuestionState.IN_PROGRESS, QuestionState.ANSWERED},
    QuestionState.IN_PROGRESS: {QuestionState.CANDIDATE_TURN, QuestionState.EVALUATING, QuestionState.FOLLOW_UP, QuestionState.ANSWERED, QuestionState.COMPLETED},
    QuestionState.CANDIDATE_TURN: {QuestionState.EVALUATING, QuestionState.ANSWERED, QuestionState.COMPLETED},
    QuestionState.EVALUATING: {QuestionState.FOLLOW_UP, QuestionState.ANSWERED, QuestionState.COMPLETED},
    QuestionState.FOLLOW_UP: {QuestionState.CANDIDATE_TURN, QuestionState.IN_PROGRESS, QuestionState.ANSWERED, QuestionState.COMPLETED},
    QuestionState.ANSWERED: {QuestionState.COMPLETED},
    QuestionState.SKIPPED: {QuestionState.COMPLETED},
    QuestionState.COMPLETED: set(),
}


def transition_session(current: str, target: SessionState) -> str:
    current_state = SessionState(current)
    if target not in SESSION_TRANSITIONS[current_state]:
        raise ValueError(f"Illegal interview session transition: {current_state.value} -> {target.value}")
    return target.value


def transition_phase(current: str, target: InterviewPhase) -> str:
    current_phase = InterviewPhase(current)
    if target not in PHASE_TRANSITIONS[current_phase]:
        raise ValueError(f"Illegal interview phase transition: {current_phase.value} -> {target.value}")
    return target.value


def transition_question(current: str, target: QuestionState) -> str:
    current_state = QuestionState(current)
    if target not in QUESTION_TRANSITIONS[current_state]:
        raise ValueError(f"Illegal interview question transition: {current_state.value} -> {target.value}")
    return target.value


from typing import Any, Callable, Optional


@dataclass
class PacingController:
    """Manages time allocation, follow-up shedding, P2/P1 skipping, and P0 grace extension (Part B8 / R3.1)."""
    duration_planned_mins: float = 20.0
    allow_grace_extension: bool = True
    pacing_strictness: str = "Balanced"
    skill_time_allocations_mins: dict[str, float] = field(default_factory=dict)
    clock_fn: Callable[[], float] = field(default=time.monotonic)
    started_monotonic: float = field(default=0.0)
    current_question_started_monotonic: float = field(default=0.0)
    grace_extended: bool = False
    grace_extension_mins: float = 5.0
    closing_reserve_secs: float = 60.0

    def __post_init__(self):
        if self.started_monotonic == 0.0:
            self.started_monotonic = self.clock_fn()
        if self.current_question_started_monotonic == 0.0:
            self.current_question_started_monotonic = self.clock_fn()

    def _now(self, now_monotonic: Optional[float] = None) -> float:
        return now_monotonic if now_monotonic is not None else self.clock_fn()

    def total_budget_seconds(self) -> float:
        extra = self.grace_extension_mins * 60.0 if self.grace_extended else 0.0
        return max(120.0, self.duration_planned_mins * 60.0 + extra)

    def elapsed_seconds(self, now_monotonic: Optional[float] = None) -> float:
        now = self._now(now_monotonic)
        return max(0.0, now - self.started_monotonic)

    def remaining_seconds(self, now_monotonic: Optional[float] = None) -> float:
        return max(0.0, self.total_budget_seconds() - self.elapsed_seconds(now_monotonic))

    def question_elapsed_seconds(self, now_monotonic: Optional[float] = None) -> float:
        now = self._now(now_monotonic)
        return max(0.0, now - self.current_question_started_monotonic)

    def mark_question_started(self, now_monotonic: Optional[float] = None) -> None:
        self.current_question_started_monotonic = self._now(now_monotonic)

    def per_question_budget_seconds(
        self,
        skill_name: Optional[str],
        allocated_questions_for_skill: int = 1,
        total_questions: int = 5,
    ) -> float:
        key = (skill_name or "").casefold()
        if key in self.skill_time_allocations_mins and self.skill_time_allocations_mins[key] > 0:
            mins = self.skill_time_allocations_mins[key] / max(1, allocated_questions_for_skill)
            return max(45.0, mins * 60.0)
        usable = max(60.0, (self.duration_planned_mins * 60.0) - self.closing_reserve_secs)
        return max(45.0, usable / max(1, total_questions))

    def maybe_grant_grace_extension(
        self,
        has_open_p0: bool,
        now_monotonic: Optional[float] = None,
    ) -> bool:
        """Grant a one-time +5m grace extension ONLY if time is nearly out and a P0 question is still open."""
        if (
            self.allow_grace_extension
            and not self.grace_extended
            and has_open_p0
            and self.remaining_seconds(now_monotonic) <= self.closing_reserve_secs
        ):
            self.grace_extended = True
            return True
        return False

    def should_allow_followup(
        self,
        *,
        current_priority: str,
        skill_name: Optional[str],
        remaining_questions_by_priority: dict[str, int],
        total_questions: int = 5,
        now_monotonic: Optional[float] = None,
    ) -> bool:
        """Drop follow-ups FIRST when behind schedule or per-question budget is exceeded."""
        rem = self.remaining_seconds(now_monotonic)
        q_elapsed = self.question_elapsed_seconds(now_monotonic)
        q_budget = self.per_question_budget_seconds(skill_name, 1, total_questions)

        if q_elapsed >= q_budget:
            return False

        p0_left = remaining_questions_by_priority.get("P0", 0)
        p1_left = remaining_questions_by_priority.get("P1", 0)
        p2_left = remaining_questions_by_priority.get("P2", 0)
        total_left = p0_left + p1_left + p2_left

        min_needed = (p0_left * 65.0) + ((p1_left + p2_left) * 45.0) + self.closing_reserve_secs
        if rem < min_needed:
            return False
        if total_left > 0 and rem <= self.closing_reserve_secs + 45.0:
            return False
        return True

    def should_allow_probe(
        self,
        section_priority: str,
        remaining_sections_priorities: list[str],
        now_monotonic: Optional[float] = None,
    ) -> bool:
        """Behind schedule drops probes first (before escalation and section shedding)."""
        rem = self.remaining_seconds(now_monotonic)
        p0_count = sum(1 for p in remaining_sections_priorities if p.upper() == "P0")
        p1_count = sum(1 for p in remaining_sections_priorities if p.upper() == "P1")
        # Need at least minimum time for remaining sections + reserve
        needed = (p0_count * 120.0) + (p1_count * 90.0) + self.closing_reserve_secs + 30.0
        return rem >= needed

    def should_allow_escalation(
        self,
        section_priority: str,
        remaining_sections_priorities: list[str],
        now_monotonic: Optional[float] = None,
    ) -> bool:
        """Behind schedule drops escalation next (after probes, before section skipping)."""
        rem = self.remaining_seconds(now_monotonic)
        p0_count = sum(1 for p in remaining_sections_priorities if p.upper() == "P0")
        # Escalation requires at least 45 seconds plus time for remaining P0 sections
        needed = (p0_count * 120.0) + self.closing_reserve_secs + 45.0
        return rem >= needed

    def should_skip_section(
        self,
        section_priority: str,
        remaining_sections_priorities: list[str],
        now_monotonic: Optional[float] = None,
    ) -> bool:
        """Shedding order: P2 dropped, then P1 dropped, NEVER P0 dropped."""
        p_tier = section_priority.upper()
        if p_tier == "P0":
            return False  # NEVER drop P0

        rem = self.remaining_seconds(now_monotonic)
        p0_count = sum(1 for p in remaining_sections_priorities if p.upper() == "P0")
        p1_count = sum(1 for p in remaining_sections_priorities if p.upper() == "P1")

        p0_needed = (p0_count * 120.0) + self.closing_reserve_secs
        p0_and_p1_needed = p0_needed + (p1_count * 90.0)

        if p_tier == "P2":
            return rem < p0_and_p1_needed
        if p_tier == "P1":
            return rem < p0_needed
        return False

    def should_wrap_up(self, has_open_p0: bool = False, now_monotonic: Optional[float] = None) -> bool:
        """Wrap up at the limit unless a one-time grace extension can be granted for an open P0."""
        self.maybe_grant_grace_extension(has_open_p0=has_open_p0, now_monotonic=now_monotonic)
        return self.remaining_seconds(now_monotonic) <= 0.0

    def select_next_question_index(
        self,
        questions: list[Any],
        current_index: int,
        now_monotonic: Optional[float] = None,
    ) -> tuple[Optional[int], list[int]]:
        """Choose the next question index to ask and return any skipped question indices."""
        remaining_indices = list(range(current_index + 1, len(questions)))
        if not remaining_indices:
            return None, []

        has_open_p0 = any(
            (getattr(questions[i], "priority_tier", "P0") or "P0").upper() == "P0"
            for i in remaining_indices
        )
        self.maybe_grant_grace_extension(has_open_p0=has_open_p0, now_monotonic=now_monotonic)

        rem = self.remaining_seconds(now_monotonic)
        p0_count = sum(
            1 for i in remaining_indices
            if (getattr(questions[i], "priority_tier", "P0") or "P0").upper() == "P0"
        )
        p1_count = sum(
            1 for i in remaining_indices
            if (getattr(questions[i], "priority_tier", "P0") or "P0").upper() == "P1"
        )

        p0_needed = (p0_count * 65.0) + self.closing_reserve_secs
        p0_and_p1_needed = p0_needed + (p1_count * 50.0)

        skip_p2 = rem < p0_and_p1_needed
        skip_p1 = rem < p0_needed

        skipped: list[int] = []
        for idx in remaining_indices:
            tier = (getattr(questions[idx], "priority_tier", "P0") or "P0").upper()
            if tier == "P2" and skip_p2:
                skipped.append(idx)
                continue
            if tier == "P1" and skip_p1:
                skipped.append(idx)
                continue
            return idx, skipped

        return None, skipped
