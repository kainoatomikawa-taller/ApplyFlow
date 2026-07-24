"""DTOs — input/output contracts for the answer-memory use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StoreAnswerInput:
    user_id: str
    question_text: str
    answer_text: str


@dataclass(frozen=True)
class AnswerMemoryOutput:
    id: str
    user_id: str
    question_text: str
    answer_text: str
    embedding: list[float]
    source: str
    created_at: datetime


@dataclass(frozen=True)
class FindSimilarAnswerInput:
    user_id: str
    question_text: str
    # Overrides AnswerSimilarityMatcher.DEFAULT_THRESHOLD when set, so
    # callers can tune match strictness without a code change.
    threshold: float | None = None


@dataclass(frozen=True)
class AnswerMatchOutput:
    """A retrieved answer paired with its similarity score and — via the
    nested `AnswerMemoryOutput.source` — its provenance."""

    answer: AnswerMemoryOutput
    similarity_score: float
