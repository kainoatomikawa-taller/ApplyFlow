"""ApplicationReviewSessions — the parked browser sessions sitting on filled
application forms, waiting for the candidate.

Why this exists
---------------
An application has to be reviewed by a person before it is sent, and the
form it is reviewed *on* is a live page in a browser. Between "ApplyFlow
filled this" and "the candidate pressed Submit" there is a human reading a
screen, which on any real timescale means several requests. Something has to
hold the filled form open across them, or the candidate's review would be of
a report whose page had already been thrown away — and submitting would mean
re-opening the portal and re-filling everything, which is a second
application's worth of risk for no benefit.

So a pass that filled a form parks its session here and gets an id back.
Answering a remaining question writes into that same page; submitting
presses that same form's button.

What it guarantees
------------------
- **Ownership.** A review is only ever handed back to the candidate it was
  parked for. An id belonging to someone else is indistinguishable from one
  that never existed (`ReviewSessionNotFoundError`).
- **Nothing is held forever.** Every review has a deadline. A candidate who
  walks away leaves a browser context and its memory behind, and a worker
  accumulating those is a worker that eventually dies — so expiry closes the
  session, and expiry is checked on every access rather than by a timer that
  may not be running.
- **One live review per form.** Parking a second review for the same
  candidate and job closes the first. Two browsers on one form for one
  person is either a double submission waiting to happen or a candidate
  reviewing a page that is no longer the one they will send.
- **A bounded number of browsers.** At capacity the oldest review is closed
  to make room, because the newest is the one a human is looking at *now*.

Process-local, and that is a real constraint
--------------------------------------------
These are live browser sessions, so they live in the process that opened
them. An API served by several workers must therefore route a review's
requests back to the worker that parked it (sticky sessions), or run the
autofill flow in a single-process deployment. A request that lands on the
wrong worker gets `ReviewSessionNotFoundError` — the same honest "run it
again" it gets for an expired session, never a silent misfill. Making the
review survive a worker restart would mean serializing a browser session,
which is not a thing; the alternative design is to re-open and re-fill on
submit, which trades this constraint for filling a real application form
twice.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.application.dtos.application_autofill_dtos import (
    ApplicationAutofillOutput,
    ApplicationBoundaryOutput,
    AutofilledFieldOutput,
    FieldAutofillOutcome,
)
from src.application.exceptions import (
    ReviewFieldNotFoundError,
    ReviewSessionNotFoundError,
)
from src.application.ports.browser_automation_port import BrowserSessionPort
from src.application.ports.id_generator_port import IdGeneratorPort

logger = logging.getLogger(__name__)

#: How long a filled form is held open for review by default. Long enough to
#: read a form's worth of questions and answer a few, short enough that a
#: candidate who closed the tab is not still costing a browser context an
#: hour later.
DEFAULT_REVIEW_TTL_SECONDS = 900.0

#: How many filled forms one process holds open at once by default. Each is
#: a browser context, which is tens of megabytes; this is a resource ceiling,
#: not a product limit.
DEFAULT_MAX_PARKED_REVIEWS = 8


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ParkedApplicationReview:
    """One filled form held open for its candidate.

    Mutable, unlike almost everything else in this codebase, and
    deliberately so: it is the state of a review in progress. Each answer
    the candidate gives updates the field it answered, so the report stays
    the one true account of what is currently typed into the page rather
    than a snapshot that drifts from it.
    """

    review_id: str
    user_id: str
    job_posting_id: str
    apply_url: str
    ats_provider: str
    session: BrowserSessionPort
    expires_at: datetime
    fields: list[AutofilledFieldOutput] = field(default_factory=list)
    screenshot_png: bytes | None = None
    boundaries: list[ApplicationBoundaryOutput] = field(default_factory=list)

    def field_by_id(self, field_id: str) -> AutofilledFieldOutput:
        """The field `field_id` names, or `ReviewFieldNotFoundError`."""
        for item in self.fields:
            if item.field_id == field_id:
                return item
        raise ReviewFieldNotFoundError(self.review_id, field_id)

    def record_answer(self, field_id: str, value: str) -> AutofilledFieldOutput:
        """Replace one field's entry with the candidate's own answer.

        The new entry is `filled`, carries no surface reason, and — the part
        that matters — is not awaiting confirmation. A value the candidate
        typed themselves is already their statement; asking them to confirm
        what they just wrote would be a gate pointing at nothing. It is
        marked `answered_by_candidate` so a reviewer, and the submit gate,
        can tell the two provenances apart.
        """
        existing = self.field_by_id(field_id)
        answered = AutofilledFieldOutput(
            field_id=existing.field_id,
            label=existing.label,
            kind=existing.kind,
            required=existing.required,
            outcome=FieldAutofillOutcome.FILLED.value,
            slot=existing.slot,
            value=value,
            is_derived=False,
            reason=None,
            detail=None,
            is_sensitive=existing.is_sensitive,
            sensitivity=existing.sensitivity,
            requires_confirmation=False,
            answered_by_candidate=True,
        )
        self.fields = [
            answered if item.field_id == field_id else item for item in self.fields
        ]
        return answered

    def to_output(self) -> ApplicationAutofillOutput:
        """This review as the report a caller renders."""
        return ApplicationAutofillOutput(
            job_posting_id=self.job_posting_id,
            apply_url=self.apply_url,
            ats_provider=self.ats_provider,
            fields=list(self.fields),
            screenshot_png=self.screenshot_png,
            boundaries=list(self.boundaries),
            review_session_id=self.review_id,
            review_expires_at=self.expires_at,
        )


class ApplicationReviewSessions:
    """The parked reviews this process is holding, keyed by review id."""

    def __init__(
        self,
        id_generator: IdGeneratorPort,
        *,
        ttl_seconds: float = DEFAULT_REVIEW_TTL_SECONDS,
        max_parked: int = DEFAULT_MAX_PARKED_REVIEWS,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._id_generator = id_generator
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_parked = max_parked
        self._now = clock
        self._parked: dict[str, ParkedApplicationReview] = {}
        #: Serializes the eviction and expiry passes so two concurrent
        #: requests cannot both decide to close the same session.
        self._lock = asyncio.Lock()

    async def park(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        apply_url: str,
        ats_provider: str,
        session: BrowserSessionPort,
        fields: list[AutofilledFieldOutput],
        screenshot_png: bytes | None,
        boundaries: list[ApplicationBoundaryOutput],
    ) -> ParkedApplicationReview:
        """Hold a filled form open and return the review that names it."""
        async with self._lock:
            await self._close_expired()
            await self._close_superseded(user_id=user_id, job_posting_id=job_posting_id)
            await self._make_room()

            review = ParkedApplicationReview(
                review_id=self._id_generator.new_id(),
                user_id=user_id,
                job_posting_id=job_posting_id,
                apply_url=apply_url,
                ats_provider=ats_provider,
                session=session,
                expires_at=self._now() + self._ttl,
                fields=list(fields),
                screenshot_png=screenshot_png,
                boundaries=list(boundaries),
            )
            self._parked[review.review_id] = review
            return review

    async def acquire(
        self, review_session_id: str, *, user_id: str
    ) -> ParkedApplicationReview:
        """The review `review_session_id` names, if it is this caller's and
        still alive.

        Expiry is enforced here rather than by a background timer: a review
        is only ever wrong to use *at the moment of use*, and a process with
        no traffic has nothing to sweep.
        """
        async with self._lock:
            await self._close_expired()
            review = self._parked.get(review_session_id)
            # Ownership and existence collapse into one answer on purpose —
            # telling an unauthorized caller that the id is real would be a
            # small oracle they have no business having.
            if review is None or review.user_id != user_id:
                raise ReviewSessionNotFoundError(review_session_id)
            return review

    async def release(self, review_session_id: str, *, user_id: str) -> None:
        """Finish with a review: close its browser and forget it.

        Called when the application has been submitted and when the
        candidate abandons it. Raises `ReviewSessionNotFoundError` for an id
        that was not theirs or is already gone, so "discard" cannot be used
        to probe for other candidates' sessions.
        """
        async with self._lock:
            review = self._parked.get(review_session_id)
            if review is None or review.user_id != user_id:
                raise ReviewSessionNotFoundError(review_session_id)
            del self._parked[review_session_id]
            await _close_quietly(review)

    async def close_all(self) -> None:
        """Close every parked review. The shutdown backstop, and idempotent.

        A browser session outliving the process that owns it is the failure
        this exists to prevent, so it mirrors `BrowserAutomationPort.shutdown`
        one layer up.
        """
        async with self._lock:
            parked, self._parked = self._parked, {}
            for review in parked.values():
                await _close_quietly(review)

    # -- internals ---------------------------------------------------------

    async def _close_expired(self) -> None:
        now = self._now()
        expired = [
            review for review in self._parked.values() if review.expires_at <= now
        ]
        for review in expired:
            logger.info(
                "Closing an expired application review (review_id=%s, "
                "job_posting_id=%s) — the candidate did not finish it in time.",
                review.review_id,
                review.job_posting_id,
            )
            del self._parked[review.review_id]
            await _close_quietly(review)

    async def _close_superseded(self, *, user_id: str, job_posting_id: str) -> None:
        """Close any review this candidate already had open on this job."""
        superseded = [
            review
            for review in self._parked.values()
            if review.user_id == user_id and review.job_posting_id == job_posting_id
        ]
        for review in superseded:
            logger.info(
                "Replacing an earlier review of the same application "
                "(review_id=%s, job_posting_id=%s).",
                review.review_id,
                review.job_posting_id,
            )
            del self._parked[review.review_id]
            await _close_quietly(review)

    async def _make_room(self) -> None:
        """Evict oldest-first until there is room for one more.

        Oldest rather than newest because the request arriving now is the one
        a person is waiting on. An evicted candidate re-runs the autofill;
        the alternative — refusing the new pass — makes the oldest abandoned
        tab in the process the thing that blocks everyone else.
        """
        while len(self._parked) >= self._max_parked:
            oldest = min(self._parked.values(), key=lambda review: review.expires_at)
            logger.warning(
                "Evicting an application review to stay within the %d parked "
                "review limit (review_id=%s).",
                self._max_parked,
                oldest.review_id,
            )
            del self._parked[oldest.review_id]
            await _close_quietly(oldest)


async def _close_quietly(review: ParkedApplicationReview) -> None:
    """Close a review's browser session, never failing the caller for it.

    The session is being discarded either way; a close that raises has
    already lost whatever it was holding, and turning that into the caller's
    error would fail a submission that had already gone through.
    """
    try:
        await review.session.close()
    except Exception as exc:  # noqa: BLE001 - cleanup must not raise
        logger.warning(
            "Failed to close the browser session for review %s: %s",
            review.review_id,
            exc,
        )
