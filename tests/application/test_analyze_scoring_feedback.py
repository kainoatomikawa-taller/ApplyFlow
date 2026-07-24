"""Tests for AnalyzeScoringFeedback — the queryable tuning-analysis path
over all recorded feedback.
"""

from __future__ import annotations

import pytest

from src.application.use_cases.analyze_scoring_feedback import (
    AnalyzeScoringFeedback,
)
from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.repositories.job_match_feedback_repository import (
    JobMatchFeedbackRepository,
)
from src.domain.value_objects.feedback_rating import FeedbackRating


def _feedback(score: int, rating: FeedbackRating, suffix: str) -> JobMatchFeedback:
    return JobMatchFeedback(
        id=f"feedback-{suffix}",
        user_id="user-1",
        job_posting_id=f"job-{suffix}",
        rating=rating,
        score_at_feedback=score,
    )


class FakeJobMatchFeedbackRepository(JobMatchFeedbackRepository):
    def __init__(self, feedback: list[JobMatchFeedback]) -> None:
        self.feedback = feedback

    async def add(self, feedback: JobMatchFeedback) -> None:
        self.feedback.append(feedback)

    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedback]:
        return [f for f in self.feedback if f.user_id == user_id][:limit]

    async def list_by_job_posting_id(
        self, job_posting_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedback]:
        return [f for f in self.feedback if f.job_posting_id == job_posting_id][:limit]

    async def list_all(self, *, limit: int = 1000) -> list[JobMatchFeedback]:
        return list(self.feedback)[:limit]


@pytest.mark.asyncio
async def test_empty_feedback_yields_no_buckets():
    use_case = AnalyzeScoringFeedback(FakeJobMatchFeedbackRepository([]))
    result = await use_case.execute()
    assert result.buckets == []


@pytest.mark.asyncio
async def test_summarizes_feedback_into_score_buckets():
    feedback = [
        _feedback(90, FeedbackRating.THUMBS_UP, "a"),
        _feedback(85, FeedbackRating.THUMBS_DOWN, "b"),
        _feedback(10, FeedbackRating.THUMBS_DOWN, "c"),
    ]
    use_case = AnalyzeScoringFeedback(FakeJobMatchFeedbackRepository(feedback))

    result = await use_case.execute()

    assert len(result.buckets) == 2
    top_bucket = next(b for b in result.buckets if b.range_start == 80)
    assert top_bucket.thumbs_up == 1
    assert top_bucket.thumbs_down == 1
    assert top_bucket.agreement_rate == 0.5

    bottom_bucket = next(b for b in result.buckets if b.range_start == 0)
    assert bottom_bucket.thumbs_up == 0
    assert bottom_bucket.thumbs_down == 1
    assert bottom_bucket.agreement_rate == 0.0


@pytest.mark.asyncio
async def test_passes_limit_through_to_the_repository():
    feedback = [_feedback(50, FeedbackRating.THUMBS_UP, str(i)) for i in range(5)]
    use_case = AnalyzeScoringFeedback(FakeJobMatchFeedbackRepository(feedback))

    result = await use_case.execute(limit=2)

    assert result.buckets[0].thumbs_up == 2
