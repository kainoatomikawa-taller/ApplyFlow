"""DTOs — input/output contracts for the gap-resolution question loop."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerateGapResolutionQuestionsInput:
    """`user_id` scopes the answer-memory lookup that suppresses gaps the
    candidate has already answered on an earlier application.
    `similarity_threshold` overrides
    `AnswerSimilarityMatcher.DEFAULT_THRESHOLD` when set, so how close
    counts as "already answered" is tunable without a code change (same
    convention as `FindSimilarAnswerInput`)."""

    user_id: str
    gaps: list[str] = field(default_factory=list)
    similarity_threshold: float | None = None


@dataclass(frozen=True)
class GapResolutionQuestionOutput:
    """One gap paired with the neutrally-phrased question generated to
    surface genuine experience against it."""

    gap: str
    question: str


@dataclass(frozen=True)
class AlreadyAnsweredGapOutput:
    """A gap that a remembered answer already covers, reported instead of
    being asked again.

    Carries only the pointer to the matched record (`answer_memory_id`)
    and the score that justified the match — never the remembered
    question or answer text. `AnswerMemory` is flagged sensitive in full
    (see that entity's docstring), so the loop's "we already know this"
    signal deliberately discloses no stored answer content; a caller that
    genuinely needs the text fetches it through the answer-memory use
    cases."""

    gap: str
    answer_memory_id: str
    similarity_score: float


@dataclass(frozen=True)
class GapResolutionQuestionsOutput:
    """The loop's plan: `questions` is what to actually ask, in input
    order; `already_answered` is every gap skipped because a remembered
    answer already covers it. Reported separately rather than silently
    dropped so a caller can tell "this candidate has no open gaps" apart
    from "these gaps were resolved on an earlier application"."""

    questions: list[GapResolutionQuestionOutput] = field(default_factory=list)
    already_answered: list[AlreadyAnsweredGapOutput] = field(default_factory=list)


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
