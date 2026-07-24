"""Tests for ListJobMatchFeedback — a candidate's own feedback history."""

from __future__ import annotations

import pytest

from src.application.use_cases.list_job_match_feedback import ListJobMatchFeedback
from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.repositories.job_match_feedback_repository import (
    JobMatchFeedbackRepository,
)
from src.domain.value_objects.feedback_rating import FeedbackRating


def _feedback(user_id: str, suffix: str) -> JobMatchFeedback:
    return JobMatchFeedback(
        id=f"feedback-{suffix}",
        user_id=user_id,
        job_posting_id=f"job-{suffix}",
        rating=FeedbackRating.THUMBS_UP,
        score_at_feedback=80,
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
async def test_returns_only_the_requesting_users_feedback():
    feedback = [_feedback("user-1", "a"), _feedback("user-2", "b")]
    use_case = ListJobMatchFeedback(FakeJobMatchFeedbackRepository(feedback))

    result = await use_case.execute("user-1")

    assert [o.id for o in result] == ["feedback-a"]


@pytest.mark.asyncio
async def test_empty_when_user_has_no_feedback():
    use_case = ListJobMatchFeedback(FakeJobMatchFeedbackRepository([]))
    result = await use_case.execute("user-1")
    assert result == []


@pytest.mark.asyncio
async def test_respects_limit():
    feedback = [_feedback("user-1", str(i)) for i in range(5)]
    use_case = ListJobMatchFeedback(FakeJobMatchFeedbackRepository(feedback))

    result = await use_case.execute("user-1", limit=2)

    assert len(result) == 2
