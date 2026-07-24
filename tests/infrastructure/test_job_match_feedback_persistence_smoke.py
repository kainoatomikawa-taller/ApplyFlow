"""Real-database smoke test for the job-match-feedback persistence layer.

Exercises `SqlAlchemyJobMatchFeedbackRepository` against an actual
Postgres connection end to end: create a job posting, record feedback
against it, then read it back by user, by posting, and in bulk. Mirrors
`test_job_posting_persistence_smoke.py`.

Skips (rather than fails) when no database is reachable, so `pytest`
still runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid

import pytest

from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.entities.job_posting import JobPosting
from src.domain.value_objects.feedback_rating import FeedbackRating
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.job_match_feedback_repository_impl import (
    SqlAlchemyJobMatchFeedbackRepository,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


@pytest.mark.asyncio
async def test_create_and_read_feedback_round_trip_against_a_real_database(
    schema_ready: None,
) -> None:
    job_posting = JobPosting(
        id=f"smoke-job-{uuid.uuid4()}",
        source="adzuna",
        company="Smoke Test Co",
        title="Backend Engineer",
        apply_url="https://smoketestco.example.com/careers/feedback",
        description="Build things.",
    )
    user_id = f"smoke-user-{uuid.uuid4()}"

    async with async_session_factory() as session:
        job_posting_repository = SqlAlchemyJobPostingRepository(session)
        await job_posting_repository.add(job_posting)

        feedback_repository = SqlAlchemyJobMatchFeedbackRepository(session)
        feedback = JobMatchFeedback(
            id=f"smoke-feedback-{uuid.uuid4()}",
            user_id=user_id,
            job_posting_id=job_posting.id,
            rating=FeedbackRating.THUMBS_UP,
            score_at_feedback=85,
        )
        await feedback_repository.add(feedback)

        by_user = await feedback_repository.list_by_user_id(user_id)
        assert len(by_user) == 1
        assert by_user[0].id == feedback.id
        assert by_user[0].rating == FeedbackRating.THUMBS_UP
        assert by_user[0].score_at_feedback == 85
        assert by_user[0].job_posting_id == job_posting.id

        by_posting = await feedback_repository.list_by_job_posting_id(job_posting.id)
        assert len(by_posting) == 1
        assert by_posting[0].id == feedback.id

        everything = await feedback_repository.list_all(limit=10_000)
        assert any(f.id == feedback.id for f in everything)


@pytest.mark.asyncio
async def test_multiple_reactions_to_the_same_job_are_all_kept(
    schema_ready: None,
) -> None:
    job_posting = JobPosting(
        id=f"smoke-job-{uuid.uuid4()}",
        source="adzuna",
        company="Smoke Test Co",
        title="Backend Engineer",
        apply_url="https://smoketestco.example.com/careers/feedback-2",
        description="Build things.",
    )
    user_id = f"smoke-user-{uuid.uuid4()}"

    async with async_session_factory() as session:
        job_posting_repository = SqlAlchemyJobPostingRepository(session)
        await job_posting_repository.add(job_posting)

        feedback_repository = SqlAlchemyJobMatchFeedbackRepository(session)
        await feedback_repository.add(
            JobMatchFeedback(
                id=f"smoke-feedback-{uuid.uuid4()}",
                user_id=user_id,
                job_posting_id=job_posting.id,
                rating=FeedbackRating.THUMBS_UP,
                score_at_feedback=85,
            )
        )
        await feedback_repository.add(
            JobMatchFeedback(
                id=f"smoke-feedback-{uuid.uuid4()}",
                user_id=user_id,
                job_posting_id=job_posting.id,
                rating=FeedbackRating.THUMBS_DOWN,
                score_at_feedback=85,
            )
        )

        by_posting = await feedback_repository.list_by_job_posting_id(job_posting.id)
        assert len(by_posting) == 2
