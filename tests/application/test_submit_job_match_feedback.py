"""Tests for SubmitJobMatchFeedback — records a candidate's thumbs-up/down
reaction to one ranked job match, tagged with the job and score context.
"""

from __future__ import annotations

import pytest

from src.application.dtos.job_match_feedback_dtos import (
    SubmitJobMatchFeedbackInput,
)
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.use_cases.submit_job_match_feedback import (
    SubmitJobMatchFeedback,
)
from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import InvalidValueError, JobPostingNotFoundError
from src.domain.repositories.job_match_feedback_repository import (
    JobMatchFeedbackRepository,
)
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.feedback_rating import FeedbackRating


def _posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "id": "job-1",
        "source": "adzuna",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://acme.example.com/careers/1",
        "description": "Build things.",
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


class FakeJobPostingRepository(JobPostingRepository):
    def __init__(self, postings: list[JobPosting]) -> None:
        self.postings = postings

    async def add(self, job_posting: JobPosting) -> None:
        self.postings.append(job_posting)

    async def update(self, job_posting: JobPosting) -> None:
        pass

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        return next((p for p in self.postings if p.id == job_posting_id), None)

    async def find_duplicate(self, **kwargs: object) -> JobPosting | None:
        return None

    async def list_due_for_staleness_check(self, **kwargs: object) -> list[JobPosting]:
        return []

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        return [p for p in self.postings if p.is_active][:limit]

    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        return [p for p in self.postings if p.requirements is None][:limit]


class FakeJobMatchFeedbackRepository(JobMatchFeedbackRepository):
    def __init__(self) -> None:
        self.added: list[JobMatchFeedback] = []

    async def add(self, feedback: JobMatchFeedback) -> None:
        self.added.append(feedback)

    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedback]:
        return [f for f in self.added if f.user_id == user_id][:limit]

    async def list_by_job_posting_id(
        self, job_posting_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedback]:
        return [f for f in self.added if f.job_posting_id == job_posting_id][:limit]

    async def list_all(self, *, limit: int = 1000) -> list[JobMatchFeedback]:
        return list(self.added)[:limit]


class SequentialIdGenerator(IdGeneratorPort):
    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> str:
        self._next += 1
        return f"feedback-{self._next}"


def _use_case(postings: list[JobPosting]) -> tuple[
    SubmitJobMatchFeedback, FakeJobMatchFeedbackRepository
]:
    feedback_repository = FakeJobMatchFeedbackRepository()
    use_case = SubmitJobMatchFeedback(
        feedback_repository=feedback_repository,
        job_posting_repository=FakeJobPostingRepository(postings),
        id_generator=SequentialIdGenerator(),
    )
    return use_case, feedback_repository


@pytest.mark.asyncio
async def test_submits_thumbs_up_feedback_and_persists_it():
    use_case, repository = _use_case([_posting()])

    result = await use_case.execute(
        SubmitJobMatchFeedbackInput(
            user_id="user-1",
            job_posting_id="job-1",
            rating="thumbs_up",
            score_at_feedback=85,
        )
    )

    assert result.id == "feedback-1"
    assert result.user_id == "user-1"
    assert result.job_posting_id == "job-1"
    assert result.rating == "thumbs_up"
    assert result.score_at_feedback == 85
    assert len(repository.added) == 1
    assert repository.added[0].rating == FeedbackRating.THUMBS_UP


@pytest.mark.asyncio
async def test_submits_thumbs_down_feedback():
    use_case, repository = _use_case([_posting()])

    result = await use_case.execute(
        SubmitJobMatchFeedbackInput(
            user_id="user-1",
            job_posting_id="job-1",
            rating="thumbs_down",
            score_at_feedback=40,
        )
    )

    assert result.rating == "thumbs_down"
    assert repository.added[0].rating == FeedbackRating.THUMBS_DOWN


@pytest.mark.asyncio
async def test_a_second_reaction_to_the_same_job_is_a_new_record_not_an_update():
    use_case, repository = _use_case([_posting()])

    await use_case.execute(
        SubmitJobMatchFeedbackInput(
            user_id="user-1",
            job_posting_id="job-1",
            rating="thumbs_up",
            score_at_feedback=85,
        )
    )
    await use_case.execute(
        SubmitJobMatchFeedbackInput(
            user_id="user-1",
            job_posting_id="job-1",
            rating="thumbs_down",
            score_at_feedback=85,
        )
    )

    assert len(repository.added) == 2


@pytest.mark.asyncio
async def test_raises_when_job_posting_does_not_exist():
    use_case, repository = _use_case([])

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(
            SubmitJobMatchFeedbackInput(
                user_id="user-1",
                job_posting_id="missing-job",
                rating="thumbs_up",
                score_at_feedback=85,
            )
        )

    assert repository.added == []


@pytest.mark.asyncio
async def test_raises_invalid_value_error_for_an_unrecognized_rating():
    use_case, repository = _use_case([_posting()])

    with pytest.raises(InvalidValueError):
        await use_case.execute(
            SubmitJobMatchFeedbackInput(
                user_id="user-1",
                job_posting_id="job-1",
                rating="meh",
                score_at_feedback=85,
            )
        )

    assert repository.added == []
