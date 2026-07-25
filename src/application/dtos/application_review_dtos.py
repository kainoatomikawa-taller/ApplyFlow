"""DTOs — input/output contracts for the review-and-submit flow.

SENSITIVE: `ReviewedAnswerOutput.value` is what goes onto a real application —
the candidate's name, email, address, and their work-authorization
declarations. The whole point of this payload is that a human reads it, so it
necessarily carries all of that; it must never be logged. Log the review id,
the posting id, and counts.

One list, in page order
-----------------------
`answers` is every question the form presented, in the order the portal
presented them, whether ApplyFlow filled it or not — the same choice
`ApplicationAutofillOutput` makes and for the same reason: five orphaned
questions with no surrounding context are much harder to answer than the form
they came from. The lists a review screen needs on top of that
(`sensitive_answers`, `blockers`, `unanswered_required`) are derived views over
that one list, so they cannot drift from it.

The submit gate travels with the payload
----------------------------------------
`blockers` is what stands between the candidate and submitting, and
`can_submit` is the single flag a button binds to. Both come from the domain
(`ApplicationReview.blockers`), and the submit route re-checks them — so a
client that ignored `can_submit` and posted anyway gets the same refusal rather
than a submission nobody consented to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.application.dtos.application_autofill_dtos import ApplicationAutofillOutput
from src.application.dtos.portal_handoff_dtos import PortalHandoffOutput


@dataclass(frozen=True)
class OpenApplicationReviewInput:
    """Open a review over the answers one fill pass produced.

    Takes the pass's report as data rather than running a pass itself. The fill
    pass is its own use case (`AutofillApplicationForm`) and the interface layer
    sequences the two, which keeps this one free of a browser: its job is
    turning a report into something a candidate can work with, and it is
    testable from a literal report.
    """

    user_id: str
    job_posting_id: str
    autofill: ApplicationAutofillOutput


@dataclass(frozen=True)
class GetApplicationReviewInput:
    """Read the review currently open for one posting."""

    user_id: str
    job_posting_id: str


@dataclass(frozen=True)
class ReviseReviewedAnswerInput:
    """One decision by the candidate about one field.

    `action` is `set`, `confirm`, or `decline`:

    - `set` writes `value` as their answer (an empty value is a decline — see
      `ReviewedAnswer.answered`);
    - `confirm` approves the answer already there, unchanged;
    - `decline` leaves the field deliberately blank.

    Validated as a string at this boundary because it arrives from a request;
    the use case resolves it or rejects it.
    """

    user_id: str
    review_id: str
    field_key: str
    action: str
    value: str = ""


@dataclass(frozen=True)
class SubmitApplicationReviewInput:
    """The candidate's own submission of one reviewed application."""

    user_id: str
    review_id: str
    #: Optional note in their words, capped by the entity.
    note: str = ""


@dataclass(frozen=True)
class ReviewedAnswerOutput:
    """One question as it stands, and how settled it is."""

    key: str
    label: str
    widget_kind: str
    value: str
    required: bool
    origin: str
    slot: str | None = None
    #: `legal_attestation` or `voluntary_self_id` when sensitive, else None. A
    #: review UI MUST flag these distinctly rather than inferring sensitivity
    #: from the slot name.
    sensitivity: str | None = None
    is_sensitive: bool = False
    #: Whether this field still waits on the candidate. Every sensitive field
    #: starts true and only a candidate action clears it.
    needs_decision: bool = False
    explanation: str = ""


@dataclass(frozen=True)
class SubmissionBlockerOutput:
    """One reason the application cannot be handed over yet."""

    kind: str
    detail: str
    field_key: str | None = None
    field_label: str = ""


@dataclass(frozen=True)
class ApplicationReviewOutput:
    """A filled application as the candidate sees it, plus the submit gate."""

    id: str
    job_posting_id: str
    #: Where the candidate goes to send it.
    apply_url: str
    ats_provider: str
    status: str
    is_open: bool
    created_at: datetime
    answers: list[ReviewedAnswerOutput] = field(default_factory=list)
    blockers: list[SubmissionBlockerOutput] = field(default_factory=list)
    #: False whenever anything in `blockers` stands, or the review is already
    #: submitted. The one flag a submit button binds to.
    can_submit: bool = False
    #: The hand-off blocking this portal, when there is one — carried in full
    #: (evidence and instructions included) so the review screen can present it
    #: without a second request.
    handoff: PortalHandoffOutput | None = None
    #: Fields the portal marked required that still have no answer. Warnings,
    #: not blockers: the `required` flag is only as good as the portal's markup
    #: (see `SubmissionBlocker`).
    unanswered_required_keys: list[str] = field(default_factory=list)
    screenshot_captured: bool = False
    submitted_at: datetime | None = None
    submission_note: str = ""


@dataclass(frozen=True)
class OpenApplicationReviewOutput:
    """The result of opening a review.

    `review` is None only when the portal is blocked by a hard stop: there is
    nothing to review because nothing was filled, and `handoff` says why. A
    caller branches on `review is None`, never on an exception — being stopped
    at a boundary is a correct outcome, not a failure.
    """

    job_posting_id: str
    review: ApplicationReviewOutput | None = None
    handoff: PortalHandoffOutput | None = None
    #: PNG of the filled form, base64-encoded by the interface layer. Proof the
    #: candidate can check the answer list against. Present only on the
    #: response from the pass that captured it — it is not stored.
    screenshot_png: bytes | None = None


@dataclass(frozen=True)
class SubmitApplicationReviewOutput:
    """What the candidate gets back when they submit.

    Carries the URL to finish on, because ApplyFlow cannot press the portal's
    submit button (the harness discovers no buttons — see
    `BrowserAutomationPort`) and must not imply that it did. The submission is
    recorded; sending it is the candidate's own act, and this is where they go
    to complete it.
    """

    review: ApplicationReviewOutput
    apply_url: str
