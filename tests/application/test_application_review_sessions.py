"""Tests for `ApplicationReviewSessions` — the filled forms held open between
"ApplyFlow filled this" and "the candidate pressed Submit".

Two things are being pinned down here, and they pull in opposite directions.
A review has to survive long enough for a person to read a form and answer
what ApplyFlow could not; and a live browser session must never outlive the
candidate's attention, because a process that accumulates abandoned browsers
is a process that dies. Every test below is on one side of that line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.dtos.application_autofill_dtos import (
    ApplicationBoundaryOutput,
    AutofilledFieldOutput,
    FieldAutofillOutcome,
)
from src.application.exceptions import (
    ReviewFieldNotFoundError,
    ReviewSessionNotFoundError,
)
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
    ParkedApplicationReview,
)
from tests.application.conftest import FakeBrowserSession, SequentialIdGenerator

GREENHOUSE_URL = "https://boards.greenhouse.io/globex/jobs/4001"


class MovableClock:
    """A clock a test can push forward, so expiry is exercised without
    waiting fifteen minutes for it."""

    def __init__(self) -> None:
        self._now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def field(
    field_id: str,
    *,
    label: str = "First Name",
    outcome: FieldAutofillOutcome = FieldAutofillOutcome.FILLED,
    required: bool = False,
    requires_confirmation: bool = False,
    is_sensitive: bool = False,
    value: str | None = "Dana",
) -> AutofilledFieldOutput:
    return AutofilledFieldOutput(
        field_id=field_id,
        label=label,
        kind="text",
        required=required,
        outcome=outcome.value,
        value=value,
        is_sensitive=is_sensitive,
        sensitivity="legal_attestation" if is_sensitive else None,
        requires_confirmation=requires_confirmation,
    )


def registry(**overrides: object) -> ApplicationReviewSessions:
    defaults: dict[str, object] = {"ttl_seconds": 900.0, "max_parked": 8}
    defaults.update(overrides)
    return ApplicationReviewSessions(
        SequentialIdGenerator("review"),
        **defaults,  # type: ignore[arg-type]
    )


async def park(
    sessions: ApplicationReviewSessions,
    *,
    user_id: str = "user-1",
    job_posting_id: str = "job-posting-1",
    session: FakeBrowserSession | None = None,
    fields: list[AutofilledFieldOutput] | None = None,
    boundaries: list[ApplicationBoundaryOutput] | None = None,
) -> tuple[ParkedApplicationReview, FakeBrowserSession]:
    browser_session = session or FakeBrowserSession()
    review = await sessions.park(
        user_id=user_id,
        job_posting_id=job_posting_id,
        apply_url=GREENHOUSE_URL,
        ats_provider="greenhouse",
        session=browser_session,
        fields=fields if fields is not None else [field("f-1")],
        screenshot_png=b"\x89PNG",
        boundaries=boundaries or [],
    )
    return review, browser_session


# ---- Parking and reading back ------------------------------------------------


async def test_a_parked_review_can_be_read_back_by_its_candidate() -> None:
    sessions = registry()
    review, browser_session = await park(sessions)

    acquired = await sessions.acquire(review.review_id, user_id="user-1")

    assert acquired is review
    assert acquired.session is browser_session
    assert browser_session.closed is False


async def test_the_report_a_review_hands_back_names_the_review() -> None:
    sessions = registry()
    review, _ = await park(
        sessions,
        boundaries=[
            ApplicationBoundaryOutput(
                kind="captcha",
                evidence="a challenge widget",
                instruction="finish it yourself",
                stopped_autofill=False,
                blocks_submission=True,
            )
        ],
    )

    output = review.to_output()

    assert output.review_session_id == review.review_id
    assert output.review_expires_at == review.expires_at
    assert output.job_posting_id == "job-posting-1"
    assert output.apply_url == GREENHOUSE_URL
    assert [item.field_id for item in output.fields] == ["f-1"]
    assert output.screenshot_png == b"\x89PNG"
    # A boundary on the page is carried through, and is what makes an
    # otherwise complete review unsubmittable here.
    assert output.can_be_submitted_here is False


# ---- Ownership ---------------------------------------------------------------


async def test_another_candidates_review_is_indistinguishable_from_no_review() -> None:
    """Ownership and existence collapse into one answer deliberately: a
    different error for "not yours" would confirm that the id is real."""
    sessions = registry()
    review, _ = await park(sessions, user_id="user-1")

    with pytest.raises(ReviewSessionNotFoundError) as caught:
        await sessions.acquire(review.review_id, user_id="user-2")

    with pytest.raises(ReviewSessionNotFoundError) as unknown:
        await sessions.acquire("review-does-not-exist", user_id="user-2")

    assert type(caught.value) is type(unknown.value)


async def test_a_review_cannot_be_discarded_by_someone_else() -> None:
    sessions = registry()
    review, browser_session = await park(sessions, user_id="user-1")

    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.release(review.review_id, user_id="user-2")

    # And it is still there for the candidate it belongs to.
    assert browser_session.closed is False
    assert await sessions.acquire(review.review_id, user_id="user-1") is review


# ---- Nothing is held forever -------------------------------------------------


async def test_an_expired_review_is_closed_and_gone() -> None:
    clock = MovableClock()
    sessions = registry(ttl_seconds=900.0, clock=clock)
    review, browser_session = await park(sessions)

    clock.advance(901)

    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.acquire(review.review_id, user_id="user-1")
    # The browser went with it — an unreachable session that is still open is
    # the leak this check exists to prevent.
    assert browser_session.closed is True


async def test_expiry_is_checked_on_use_rather_than_by_a_timer() -> None:
    """A process with no traffic has nothing to sweep, so the sweep happens
    where it matters: on the next access."""
    clock = MovableClock()
    sessions = registry(ttl_seconds=60.0, clock=clock)
    stale, stale_session = await park(sessions, job_posting_id="job-1")

    clock.advance(61)
    assert stale_session.closed is False  # nothing has run yet

    # Parking anything sweeps what has expired.
    await park(sessions, job_posting_id="job-2")
    assert stale_session.closed is True
    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.acquire(stale.review_id, user_id="user-1")


async def test_a_review_lives_right_up_to_its_deadline() -> None:
    clock = MovableClock()
    sessions = registry(ttl_seconds=900.0, clock=clock)
    review, _ = await park(sessions)

    clock.advance(899)

    assert await sessions.acquire(review.review_id, user_id="user-1") is review


async def test_releasing_a_review_closes_its_browser() -> None:
    sessions = registry()
    review, browser_session = await park(sessions)

    await sessions.release(review.review_id, user_id="user-1")

    assert browser_session.closed is True
    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.acquire(review.review_id, user_id="user-1")
    # Releasing twice is a caller error, not a way to close someone else's.
    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.release(review.review_id, user_id="user-1")


async def test_a_failed_close_does_not_fail_the_caller() -> None:
    """The session is being discarded either way. Turning a failed close into
    the caller's error would fail a submission that already went through."""

    class RefusesToClose(FakeBrowserSession):
        async def close(self) -> None:
            raise RuntimeError("the browser was already gone")

    sessions = registry()
    review, _ = await park(sessions, session=RefusesToClose())

    await sessions.release(review.review_id, user_id="user-1")

    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.acquire(review.review_id, user_id="user-1")


async def test_close_all_closes_every_parked_review() -> None:
    sessions = registry()
    _, first = await park(sessions, job_posting_id="job-1")
    _, second = await park(sessions, user_id="user-2", job_posting_id="job-2")

    await sessions.close_all()
    await sessions.close_all()  # idempotent

    assert first.closed is True
    assert second.closed is True


# ---- One review per form, and a bounded number of them -----------------------


async def test_a_second_pass_on_the_same_form_replaces_the_first() -> None:
    """Two browsers on one form for one candidate is either a double
    submission waiting to happen or a review of a page they will not send."""
    sessions = registry()
    first, first_session = await park(sessions, job_posting_id="job-1")
    second, second_session = await park(sessions, job_posting_id="job-1")

    assert first_session.closed is True
    assert second_session.closed is False
    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.acquire(first.review_id, user_id="user-1")
    assert await sessions.acquire(second.review_id, user_id="user-1") is second


async def test_reviews_of_different_jobs_coexist() -> None:
    sessions = registry()
    first, first_session = await park(sessions, job_posting_id="job-1")
    second, _ = await park(sessions, job_posting_id="job-2")

    assert first_session.closed is False
    assert await sessions.acquire(first.review_id, user_id="user-1") is first
    assert await sessions.acquire(second.review_id, user_id="user-1") is second


async def test_at_capacity_the_oldest_review_makes_room_for_the_newest() -> None:
    """Oldest-first, because the request arriving now is the one a person is
    waiting on. Refusing the new pass would let the oldest abandoned tab in
    the process block everyone else."""
    sessions = registry(max_parked=2)
    oldest, oldest_session = await park(sessions, job_posting_id="job-1")
    kept, kept_session = await park(sessions, job_posting_id="job-2")

    newest, newest_session = await park(sessions, job_posting_id="job-3")

    assert oldest_session.closed is True
    assert kept_session.closed is False
    assert newest_session.closed is False
    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.acquire(oldest.review_id, user_id="user-1")
    assert await sessions.acquire(kept.review_id, user_id="user-1") is kept
    assert await sessions.acquire(newest.review_id, user_id="user-1") is newest


# ---- Recording the candidate's own answers -----------------------------------


async def test_an_answer_the_candidate_gave_needs_no_confirmation() -> None:
    """The confirmation gate exists for values ApplyFlow derived from stored
    data. A value the candidate just typed is already their statement."""
    sessions = registry()
    review, _ = await park(
        sessions,
        fields=[
            field(
                "f-visa",
                label="Visa type",
                outcome=FieldAutofillOutcome.SURFACED,
                is_sensitive=True,
                requires_confirmation=False,
                value=None,
            )
        ],
    )

    answered = review.record_answer("f-visa", "H-1B")

    assert answered.value == "H-1B"
    assert answered.outcome == FieldAutofillOutcome.FILLED.value
    assert answered.answered_by_candidate is True
    assert answered.requires_confirmation is False
    # Still flagged sensitive: a review screen must keep rendering it as the
    # legal question it is.
    assert answered.is_sensitive is True
    assert answered.was_applied is True


async def test_an_answer_replaces_the_field_in_place_and_keeps_page_order() -> None:
    sessions = registry()
    review, _ = await park(
        sessions,
        fields=[field("f-1", label="First"), field("f-2", label="Second"),
                field("f-3", label="Third")],
    )

    review.record_answer("f-2", "answered")

    assert [item.field_id for item in review.fields] == ["f-1", "f-2", "f-3"]
    assert review.field_by_id("f-2").value == "answered"
    assert review.to_output().fields[1].value == "answered"


async def test_an_unknown_field_id_is_refused() -> None:
    sessions = registry()
    review, _ = await park(sessions)

    with pytest.raises(ReviewFieldNotFoundError):
        review.field_by_id("f-not-on-this-form")
    with pytest.raises(ReviewFieldNotFoundError):
        review.record_answer("f-not-on-this-form", "anything")
