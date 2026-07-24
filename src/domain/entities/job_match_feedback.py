"""JobMatchFeedback entity — a candidate's thumbs-up/down reaction to one
ranked job match, captured alongside the job and the score they saw.

Append-only by design: a candidate can react to the same job more than
once (e.g. after a later ranking run changes its score), and each
reaction is its own record rather than an overwritten "current" state —
the history of reactions over time is exactly the signal a future
scoring-tuning pass needs. See `JobMatchFeedbackRepository`'s docstring
for the full tuning-signal contract this feeds into.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.feedback_rating import FeedbackRating


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class JobMatchFeedback:
    """One thumbs-up/down reaction to a ranked job match."""

    id: str
    user_id: str
    job_posting_id: str
    rating: FeedbackRating
    #: The fit score (0-100, see `SoftPreferenceEvaluation.fit_score`) the
    #: candidate saw at the moment they reacted — the "score context"
    #: this feedback is judging, not a live re-computation.
    score_at_feedback: int
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("JobMatchFeedback requires a non-empty id.")
        if not self.user_id:
            raise InvalidValueError("JobMatchFeedback requires a non-empty user_id.")
        if not self.job_posting_id:
            raise InvalidValueError(
                "JobMatchFeedback requires a non-empty job_posting_id."
            )
        if not isinstance(self.rating, FeedbackRating):
            raise InvalidValueError("JobMatchFeedback requires a valid FeedbackRating.")
        if not 0 <= self.score_at_feedback <= 100:
            raise InvalidValueError(
                "JobMatchFeedback.score_at_feedback must be between 0 and 100."
            )
