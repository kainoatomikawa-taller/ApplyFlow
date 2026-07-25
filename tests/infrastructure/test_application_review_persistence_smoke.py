"""Real-database smoke test for the application-review store.

Exercises `SqlAlchemyApplicationReviewRepository` against an actual Postgres
connection end to end: open a review over a filled form, read it back with every
answer and decision intact, settle a sensitive field, submit it, and list a
candidate's reviews. Also proves the three properties an in-memory fake cannot
check — the partial unique index really does allow only one review *in progress*
per posting, superseding leaves a submitted review alone, and `update` on a row
that no longer exists refuses instead of inserting one.

Skips (rather than fails) when no database is reachable, so `pytest` still runs
for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.exc import IntegrityError

from src.domain.entities.application_review import ApplicationReview
from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import ApplicationReviewNotFoundError
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    FieldSensitivity,
)
from src.domain.value_objects.review_status import ReviewStatus
from src.domain.value_objects.reviewed_answer import AnswerOrigin, ReviewedAnswer
from src.infrastructure.persistence.application_review_repository_impl import (
    SqlAlchemyApplicationReviewRepository,
)
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)

_ANSWERS = (
    ReviewedAnswer(
        key="f0",
        label="Full name",
        widget_kind="text",
        value="Dana Reyes",
        slot=ApplicationFieldSlot.FULL_NAME,
        required=True,
        origin=AnswerOrigin.AUTOFILLED,
    ),
    ReviewedAnswer(
        key="f1",
        label="Are you authorized to work in the US?",
        widget_kind="radio",
        value="Yes",
        slot=ApplicationFieldSlot.WORK_AUTHORIZATION,
        sensitivity=FieldSensitivity.LEGAL_ATTESTATION,
        required=True,
        origin=AnswerOrigin.AUTOFILLED,
    ),
    ReviewedAnswer(
        key="f2",
        label="Gender",
        widget_kind="select",
        slot=ApplicationFieldSlot.EEO_SELF_IDENTIFICATION,
        sensitivity=FieldSensitivity.VOLUNTARY_SELF_ID,
        explanation="ApplyFlow never answers this one.",
    ),
)


@pytest.fixture
async def schema_ready() -> AsyncIterator[None]:
    # The process-wide engine's pool outlives a test but its connections are
    # bound to the loop that opened them, so a pooled connection from the
    # previous test is unusable here. Disposing on both sides of each test means
    # every one of them opens its own.
    await engine.dispose()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")
    yield
    await engine.dispose()


async def _job_posting() -> JobPosting:
    posting = JobPosting(
        id=f"smoke-job-{uuid.uuid4()}",
        source="greenhouse",
        company="Smoke Test Co",
        title="Backend Engineer",
        apply_url="https://boards.greenhouse.io/smoketestco/jobs/1",
        description="Build things.",
    )
    async with async_session_factory() as session:
        await SqlAlchemyJobPostingRepository(session).add(posting)
    return posting


def _review(*, user_id: str, job_posting_id: str) -> ApplicationReview:
    return ApplicationReview.open_for(
        review_id=f"smoke-review-{uuid.uuid4()}",
        user_id=user_id,
        job_posting_id=job_posting_id,
        apply_url="https://boards.greenhouse.io/smoketestco/jobs/1",
        ats_provider="greenhouse",
        answers=_ANSWERS,
        screenshot_captured=True,
    )


@pytest.mark.asyncio
async def test_a_review_round_trips_against_a_real_database(
    schema_ready: None,
) -> None:
    posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"
    review = _review(user_id=user_id, job_posting_id=posting.id)

    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationReviewRepository(session)
        await repository.add(review)

        # Every answer survives the JSON column with its provenance and its
        # sensitivity — losing either would render a legal declaration as an
        # ordinary text box on the review screen.
        stored = await repository.get_by_id(review.id)
        assert stored is not None
        assert stored.status is ReviewStatus.IN_REVIEW
        assert [answer.key for answer in stored.answers] == ["f0", "f1", "f2"]
        assert stored.answer("f0").origin is AnswerOrigin.AUTOFILLED
        assert stored.answer("f1").sensitivity is FieldSensitivity.LEGAL_ATTESTATION
        assert stored.answer("f2").is_voluntary_self_id is True
        assert stored.answer("f2").explanation == "ApplyFlow never answers this one."
        assert stored.screenshot_captured is True

        # "What am I in the middle of for this job?"
        active = await repository.get_active_for_job(
            user_id=user_id, job_posting_id=posting.id
        )
        assert active is not None and active.id == review.id

        # Both sensitive fields still await the candidate, so it cannot submit.
        assert len(stored.answers_awaiting_decision) == 2
        assert stored.can_submit(has_open_handoff=False) is False

        # The candidate settles them, and the decisions persist.
        settled = stored.with_confirmation("f1").with_declined("f2")
        await repository.update(settled)
        reread = await repository.get_by_id(review.id)
        assert reread is not None
        assert reread.answers_awaiting_decision == ()
        assert reread.answer("f2").origin is AnswerOrigin.DECLINED
        assert reread.answer("f2").value == ""
        assert reread.can_submit(has_open_handoff=False) is True

        # And submitting is recorded, after which it is no longer "active".
        await repository.update(
            reread.record_submission(has_open_handoff=False, note="sent it")
        )
        submitted = await repository.get_by_id(review.id)
        assert submitted is not None
        assert submitted.status is ReviewStatus.SUBMITTED_BY_USER
        assert submitted.submitted_at is not None
        assert submitted.submission_note == "sent it"
        assert (
            await repository.get_active_for_job(
                user_id=user_id, job_posting_id=posting.id
            )
            is None
        )


@pytest.mark.asyncio
async def test_only_one_review_in_progress_per_posting_is_allowed(
    schema_ready: None,
) -> None:
    """Enforced by the database, not only by the writer: two would mean two sets
    of answers for one application with nothing to say which was meant."""
    posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"

    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationReviewRepository(session)
        await repository.add(_review(user_id=user_id, job_posting_id=posting.id))

        with pytest.raises(IntegrityError):
            await repository.add(_review(user_id=user_id, job_posting_id=posting.id))


@pytest.mark.asyncio
async def test_superseding_replaces_a_draft_and_spares_a_submission(
    schema_ready: None,
) -> None:
    posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"

    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationReviewRepository(session)

        # A submitted review is a record of what was sent, so superseding must
        # not touch it — and it must not block the next application either.
        first = _review(user_id=user_id, job_posting_id=posting.id)
        await repository.add(first)
        await repository.update(
            first.with_confirmation("f1")
            .with_declined("f2")
            .record_submission(has_open_handoff=False)
        )

        draft = _review(user_id=user_id, job_posting_id=posting.id)
        await repository.add(draft)
        await repository.supersede_active(
            user_id=user_id, job_posting_id=posting.id
        )

        assert await repository.get_by_id(draft.id) is None
        surviving = await repository.get_by_id(first.id)
        assert surviving is not None
        assert surviving.status is ReviewStatus.SUBMITTED_BY_USER
        assert len(await repository.list_for_user(user_id)) == 1


@pytest.mark.asyncio
async def test_the_list_is_scoped_to_the_candidate_and_newest_first(
    schema_ready: None,
) -> None:
    first_posting = await _job_posting()
    second_posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"
    older = _review(user_id=user_id, job_posting_id=first_posting.id)
    newer = _review(user_id=user_id, job_posting_id=second_posting.id)

    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationReviewRepository(session)
        await repository.add(older)
        await repository.add(newer)
        await repository.add(
            _review(
                user_id=f"smoke-user-{uuid.uuid4()}",
                job_posting_id=first_posting.id,
            )
        )

        listed = await repository.list_for_user(user_id)

        assert [item.id for item in listed] == [newer.id, older.id]


@pytest.mark.asyncio
async def test_updating_a_review_that_no_longer_exists_is_refused(
    schema_ready: None,
) -> None:
    posting = await _job_posting()
    review = _review(
        user_id=f"smoke-user-{uuid.uuid4()}", job_posting_id=posting.id
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationReviewRepository(session)

        with pytest.raises(ApplicationReviewNotFoundError):
            await repository.update(review)

        assert await repository.get_by_id(review.id) is None
