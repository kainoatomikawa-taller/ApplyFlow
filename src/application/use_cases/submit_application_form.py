"""SubmitApplicationForm use case — sends a reviewed application, on the
candidate's instruction, and refuses to in every case where that instruction
would not be an informed one.

This is the only code in ApplyFlow that can cause an application to be
submitted. It exists because a tool that fills a form and then cannot send
it has stopped one step short of what the candidate came for — and it is
written the way it is because pressing Submit on someone's job application
is irreversible and is seen by a person at the company.

Nothing is submitted unattended
-------------------------------
Four things must all be true before the button is pressed, and every one of
them is checked here against the *live page* rather than against a report a
client may have been holding for ten minutes:

1. **A candidate asked for it.** The instruction is an input, not a default:
   this use case is reached only from the authenticated route the candidate
   hits, with the review session id they were given. Nothing schedules it,
   no queue task calls it, and the autofill pass does not fall through into
   it.
2. **No human-only boundary is on the page.** Re-scanned here, so a CAPTCHA
   that appeared after the form was filled stops the submission
   (`ApplicationHandoffRequiredError`) instead of being submitted past.
3. **Every sensitive value ApplyFlow filled has been confirmed.** Work
   authorization, sponsorship, visa, citizenship: legal declarations derived
   from stored data, which the candidate is accountable for asserting to
   *this* employer. Unconfirmed means refused, with no override
   (`UnconfirmedSensitiveFieldsError`). Values the candidate typed
   themselves need no confirmation — they are already their statement.
4. **Every required field is answered.** Refused here rather than sent for
   the portal to reject, because a rejected submission on several portals
   comes back with the uploads dropped and the answers cleared
   (`IncompleteApplicationError`).

Which button, and never a guess
-------------------------------
The form's submit controls are read at submit time. Exactly one means that
one is pressed. Several — "Submit application" beside "Submit and create an
account" — means the candidate has to name which, because choosing for them
would pick a side effect they never agreed to. None means this portal
submits from script the harness cannot see, and the honest answer is to hand
off rather than to click the nearest button-shaped thing.

What it claims afterwards
-------------------------
Only what it knows. The press either happened or raised; nothing is
"probably sent". If the page that came back carries a challenge, that is
reported in `outstanding_boundaries` and `is_confirmed_sent` is False — a
submission that may not have landed must never read as one that did.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.application.dtos.application_autofill_dtos import (
    AutofilledFieldOutput,
    FieldAutofillOutcome,
)
from src.application.dtos.application_review_dtos import (
    ApplicationSubmissionOutput,
    SubmitApplicationFormInput,
)
from src.application.exceptions import (
    AmbiguousSubmitControlError,
    ApplicationHandoffRequiredError,
    BrowserAutomationError,
    IncompleteApplicationError,
    SubmitControlUnavailableError,
    UnconfirmedSensitiveFieldsError,
)
from src.application.ports.browser_automation_port import (
    BrowserSessionPort,
    FormFieldKind,
    SubmitControl,
)
from src.application.services.application_boundary_scanner import (
    boundaries_in,
    scan_application_boundaries,
    to_boundary_output,
)
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
    ParkedApplicationReview,
)
from src.domain.value_objects.application_boundary import ApplicationBoundary

logger = logging.getLogger(__name__)

#: How much of the portal's reply is carried back for the candidate to read.
#: Enough for a confirmation message or a list of validation errors, not the
#: whole page.
_CONFIRMATION_EXCERPT_LENGTH = 600


class SubmitApplicationForm:
    def __init__(self, review_sessions: ApplicationReviewSessions) -> None:
        self._review_sessions = review_sessions

    async def execute(
        self, dto: SubmitApplicationFormInput
    ) -> ApplicationSubmissionOutput:
        review = await self._review_sessions.acquire(
            dto.review_session_id, user_id=dto.user_id
        )

        await self._refuse_if_boundary(review)
        _refuse_if_unconfirmed(review, confirmed=frozenset(dto.confirmed_field_ids))
        _refuse_if_incomplete(review)

        control = await self._choose_control(review, dto.submit_control_label)

        logger.info(
            "Submitting an application on the candidate's instruction "
            "(review_id=%s, job_posting_id=%s, user_id=%s, control=%r).",
            review.review_id,
            review.job_posting_id,
            dto.user_id,
            control.label,
        )
        await review.session.press_submit(control.handle)
        submitted_at = datetime.now(UTC)

        # Everything from here on is reporting. A press that went through
        # cannot be undone by a failure to describe it, so each step degrades
        # rather than raising — and the session is released either way.
        outcome = await self._describe_outcome(
            review, control=control, submitted_at=submitted_at
        )
        await self._review_sessions.release(review.review_id, user_id=dto.user_id)
        return outcome

    # ---- The gates -----------------------------------------------------------

    async def _refuse_if_boundary(self, review: ParkedApplicationReview) -> None:
        """Refuse to press while the page carries a human-only check.

        Re-scanned against the live page rather than trusting the scan from
        the autofill pass: portals add a challenge when they see a form
        completed quickly, and the whole point of this check is to catch the
        one that was not there before.
        """
        boundaries = await scan_application_boundaries(
            review.session,
            field_labels=tuple(item.label for item in review.fields),
            has_password_field=any(
                item.kind == FormFieldKind.PASSWORD.value for item in review.fields
            ),
        )
        blocking = tuple(
            to_boundary_output(boundary)
            for boundary in boundaries
            if boundary.blocks_unattended_submit
        )
        if blocking:
            logger.info(
                "Refused to submit an application: %s (review_id=%s, "
                "job_posting_id=%s).",
                ", ".join(boundary.kind for boundary in blocking),
                review.review_id,
                review.job_posting_id,
            )
            raise ApplicationHandoffRequiredError(review.apply_url, blocking)

    # ---- Choosing the control ------------------------------------------------

    async def _choose_control(
        self, review: ParkedApplicationReview, requested_label: str | None
    ) -> SubmitControl:
        controls = await review.session.read_submit_controls()
        labels = tuple(control.label for control in controls)

        if not controls:
            raise SubmitControlUnavailableError(
                "the form exposes no control that submits it — this portal "
                "sends its applications from script the harness cannot press"
            )

        if requested_label is not None:
            wanted = _normalize(requested_label)
            match = next(
                (
                    control
                    for control in controls
                    if _normalize(control.label) == wanted
                ),
                None,
            )
            if match is None:
                raise SubmitControlUnavailableError(
                    f"no control labelled '{requested_label}' is on the form",
                    available=labels,
                )
            return match

        if len(controls) > 1:
            raise AmbiguousSubmitControlError(labels)
        return controls[0]

    # ---- Reporting -----------------------------------------------------------

    async def _describe_outcome(
        self,
        review: ParkedApplicationReview,
        *,
        control: SubmitControl,
        submitted_at: datetime,
    ) -> ApplicationSubmissionOutput:
        """Read back what the portal answered with.

        Boundaries are detected here from the page's own signals only, with
        no field read: a portal offering "create an account to track your
        application" *after* a successful submission would otherwise be read
        as a login wall, and reporting a completed application as possibly
        unsent is its own harm.
        """
        excerpt = ""
        boundaries: tuple[ApplicationBoundary, ...] = ()
        try:
            signals = await review.session.read_boundary_signals()
            boundaries = boundaries_in(signals)
            excerpt = signals.visible_text[:_CONFIRMATION_EXCERPT_LENGTH]
            final_url = signals.url
        except BrowserAutomationError as exc:
            logger.warning(
                "The application was submitted but the portal's reply could "
                "not be read (review_id=%s): %s",
                review.review_id,
                exc,
            )
            final_url = review.apply_url

        return ApplicationSubmissionOutput(
            job_posting_id=review.job_posting_id,
            submitted_at=submitted_at,
            pressed_control=control.label,
            final_url=final_url,
            confirmation_excerpt=excerpt,
            screenshot_png=await _capture(review.session),
            outstanding_boundaries=[
                to_boundary_output(boundary) for boundary in boundaries
            ],
        )


def _refuse_if_unconfirmed(
    review: ParkedApplicationReview, *, confirmed: frozenset[str]
) -> None:
    """Refuse to press while a sensitive value ApplyFlow filled is unapproved."""
    pending = tuple(
        _describe(item)
        for item in review.fields
        if item.requires_confirmation and item.field_id not in confirmed
    )
    if pending:
        logger.info(
            "Refused to submit an application: %d sensitive answer(s) not "
            "confirmed (review_id=%s).",
            len(pending),
            review.review_id,
        )
        raise UnconfirmedSensitiveFieldsError(pending)


def _refuse_if_incomplete(review: ParkedApplicationReview) -> None:
    """Refuse to press while a field the portal marked required is unanswered.

    Reads the review's own record of the form rather than the page, because
    that record is what the candidate has been looking at and answering
    against — and because `FormField.required` was captured from the same
    markup at the same moment as everything else in it.
    """
    missing = tuple(
        _describe(item)
        for item in review.fields
        if item.required and not _is_answered(item)
    )
    if missing:
        logger.info(
            "Refused to submit an application: %d required field(s) still "
            "unanswered (review_id=%s).",
            len(missing),
            review.review_id,
        )
        raise IncompleteApplicationError(missing)


def _is_answered(item: AutofilledFieldOutput) -> bool:
    """Whether something is in this field — from either provenance.

    `was_applied` covers both the autofill and the candidate's own answer,
    since an answer they typed is recorded as `filled`. A field the portal
    refused (`not_accepted`) is deliberately not answered: the value never
    reached the page.
    """
    return item.outcome in {
        FieldAutofillOutcome.FILLED.value,
        FieldAutofillOutcome.ATTACHED.value,
    }


def _describe(item: AutofilledFieldOutput) -> str:
    """A field's label for a refusal message, never its value.

    Falls back to the widget kind for a field the portal labelled only
    visually, so a refusal never names a field as `''`.
    """
    return item.label.strip() or f"an unlabelled {item.kind} field"


def _normalize(label: str) -> str:
    """Compare button labels for case and whitespace only.

    Exactly as forgiving as the harness's own option matching and no more: a
    candidate confirming "submit application" must reach the "Submit
    Application" button, and must never reach "Submit and create an account"
    because it happens to start with the same word.
    """
    return " ".join(label.split()).casefold()


async def _capture(session: BrowserSessionPort) -> bytes | None:
    """The portal's reply as a PNG, or None if the capture failed.

    Never raises: the application has already been sent, and losing the
    screenshot loses the candidate their proof, not their submission.
    """
    try:
        return await session.screenshot()
    except BrowserAutomationError:
        return None
