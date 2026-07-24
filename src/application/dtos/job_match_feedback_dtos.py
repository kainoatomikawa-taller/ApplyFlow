"""DTOs — input/output contracts for the job-match-feedback use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SubmitJobMatchFeedbackInput:
    user_id: str
    job_posting_id: str
    rating: str
    score_at_feedback: int


@dataclass(frozen=True)
class JobMatchFeedbackOutput:
    id: str
    user_id: str
    job_posting_id: str
    rating: str
    score_at_feedback: int
    created_at: datetime


@dataclass(frozen=True)
class ScoreBucketAgreementOutput:
    range_start: int
    range_end: int
    thumbs_up: int
    thumbs_down: int
    agreement_rate: float | None


@dataclass(frozen=True)
class ScoringFeedbackSummaryOutput:
    buckets: list[ScoreBucketAgreementOutput] = field(default_factory=list)
