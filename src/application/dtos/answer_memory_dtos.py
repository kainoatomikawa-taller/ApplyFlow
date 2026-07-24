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
