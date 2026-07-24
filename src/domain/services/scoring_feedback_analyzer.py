"""ScoringFeedbackAnalyzer — a pure domain service that turns raw
thumbs-up/down feedback into the signal a scoring-tuning pass consumes.

This is the documented, working path from `JobMatchFeedback` records back
into scoring: it buckets feedback by the score the candidate saw
(`score_at_feedback`) and computes each bucket's real agreement rate
(the thumbs-up share). If a high-scoring bucket (e.g. 80-100) has a low
agreement rate, that is a concrete signal that `SoftPreferenceEvaluator`
is over-scoring matches candidates don't actually want; if a low-scoring
bucket has a high agreement rate, it's under-scoring ones they do.

Actually recalibrating `SoftPreferenceEvaluator`'s weights from this
signal is future work — this service is the first, testable step of that
pipeline: turning a list of individual reactions into the aggregate a
human (or a future automated tuner) can act on.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.value_objects.feedback_rating import FeedbackRating

#: Width of each score band feedback is grouped into. Five bands cover
#: the 0-100 fit-score range: [0,20), [20,40), [40,60), [60,80), [80,100].
_BUCKET_SIZE = 20
_MAX_BUCKET_START = 100 - _BUCKET_SIZE


@dataclass(frozen=True)
class ScoreBucketAgreement:
    """One score band's feedback tally and resulting agreement rate."""

    range_start: int
    range_end: int
    thumbs_up: int = 0
    thumbs_down: int = 0

    @property
    def total(self) -> int:
        return self.thumbs_up + self.thumbs_down

    @property
    def agreement_rate(self) -> float | None:
        """Share of this bucket's feedback that was thumbs-up, or None if
        the bucket has no feedback yet to judge — silence, not a 0%
        agreement claim, when there's nothing to base one on."""
        if self.total == 0:
            return None
        return self.thumbs_up / self.total


class ScoringFeedbackAnalyzer:
    """Buckets feedback by score and computes each bucket's agreement rate."""

    def analyze(
        self, feedback: list[JobMatchFeedback]
    ) -> tuple[ScoreBucketAgreement, ...]:
        tallies: dict[int, dict[str, int]] = {}
        for entry in feedback:
            bucket_start = min(
                entry.score_at_feedback // _BUCKET_SIZE * _BUCKET_SIZE,
                _MAX_BUCKET_START,
            )
            counts = tallies.setdefault(bucket_start, {"up": 0, "down": 0})
            key = "up" if entry.rating == FeedbackRating.THUMBS_UP else "down"
            counts[key] += 1

        return tuple(
            ScoreBucketAgreement(
                range_start=start,
                range_end=min(start + _BUCKET_SIZE, 100),
                thumbs_up=tallies[start]["up"],
                thumbs_down=tallies[start]["down"],
            )
            for start in sorted(tallies)
        )
