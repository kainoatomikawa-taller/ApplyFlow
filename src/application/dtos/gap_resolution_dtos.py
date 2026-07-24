"""DTOs — input/output contracts for the gap-resolution question loop."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerateGapResolutionQuestionsInput:
    gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GapResolutionQuestionOutput:
    """One gap paired with the neutrally-phrased question generated to
    surface genuine experience against it."""

    gap: str
    question: str


@dataclass(frozen=True)
class ResolveGapAnswerInput:
    user_id: str
    gap: str
    question_text: str
    answer_text: str


@dataclass(frozen=True)
class ResolveGapAnswerOutput:
    """`captured=False` means the candidate's response was a decline (see
    `GapAnswerPolicy`) — the gap was cleanly omitted, nothing was
    persisted, and `answer_memory_id` stays `None`."""

    gap: str
    captured: bool
    answer_memory_id: str | None = None
