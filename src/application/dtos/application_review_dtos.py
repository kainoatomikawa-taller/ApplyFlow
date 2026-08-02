"""DTOs — input/output contracts for the review-and-submit flow.

Two review flows share this module, and they are not duplicates
---------------------------------------------------------------
ApplyFlow reviews a filled application in two different situations, and each
has its own contracts here:

- the **persisted review** (`OpenApplicationReviewInput` and the
  `ApplicationReviewOutput` family) — the answers are stored, the candidate
  comes back to them later, and submitting *records* their own act on a portal
  ApplyFlow cannot press for them;
- the **parked review** (`AnswerApplicationFieldInput`,
  `SubmitApplicationFormInput`, `ApplicationSubmissionOutput`) — a live browser
  session is held open on a supported ATS, and submitting presses that form's
  own button with the candidate watching.

Which one applies is decided by the portal, not by preference: a form
ApplyFlow can drive end to end gets the second, everything else gets the
first. They are kept in one module because they answer the same question — "is
this application ready to send?" — and splitting them invited the drift that
put two different `can_submit` rules in front of one candidate.

SENSITIVE: `ReviewedAnswerOutput.value` is what goes onto a real application —
the candidate's name, email, address, and their work-authorization
declarations — and `AnswerApplicationFieldInput.value` is whatever they typed
into a field on a real form, routinely their address, their salary
expectation, or their EEO self-identification (answering EEO themselves is the
*only* way it is ever answered). The whole point of these payloads is that a
human reads them, so they necessarily carry all of that; they must never be
logged. Log the review id, the posting id, the field id, and counts.

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

from src.application.dtos.application_autofill_dtos import (
    ApplicationAutofillOutput,
    ApplicationBoundaryOutput,
)
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


# -- The parked review: a live form, submitted with the candidate watching ----
#
# Sending is the candidate's act, and this is where that is enforced. There is
# exactly one input type that can lead to a submission
# (`SubmitApplicationFormInput`), it names one parked review session, and it
# carries the candidate's confirmation of every sensitive value ApplyFlow
# filled. Nothing constructs one on a schedule, from a queue, or as a
# follow-on step of an autofill pass: the only caller is the authenticated
# route the candidate hits when they press Submit. "Nothing is submitted
# unattended" is that shape — a human instruction is a required input, not a
# default.


@dataclass(frozen=True)
class AnswerApplicationFieldInput:
    """The candidate's own answer to one field on the parked form.

    Used for the questions ApplyFlow refused to answer for them: a company
    screening question, a legal field the record does not settle, and EEO
    self-identification — which reaches a form through this path or not at
    all.
    """

    user_id: str
    review_session_id: str
    field_id: str
    value: str


@dataclass(frozen=True)
class DiscardApplicationReviewInput:
    """Abandon a parked review session and close its browser."""

    user_id: str
    review_session_id: str


@dataclass(frozen=True)
class SubmitApplicationFormInput:
    """The candidate's instruction to send the application now.

    `confirmed_field_ids` are the sensitive values they have looked at and
    approved. It is a required input rather than a flag with a default,
    because a default would mean a caller could submit legal declarations
    the candidate never saw — which is exactly the failure the confirmation
    gate exists to prevent.

    `submit_control_label` names which button to press, and only has to be
    given when the form offers more than one way to send it. Named by label
    rather than by id because a label is what the candidate saw and what
    stays stable between reads of the page.
    """

    user_id: str
    review_session_id: str
    confirmed_field_ids: tuple[str, ...] = ()
    submit_control_label: str | None = None


@dataclass(frozen=True)
class ApplicationSubmissionOutput:
    """What happened when the application was sent.

    Deliberately does not claim more than it knows. `pressed_control` and
    `final_url` are facts about what ApplyFlow did; `confirmation_excerpt`
    is what the portal said back, for the candidate to read. If the portal
    answered with a challenge instead of a confirmation, that is reported in
    `outstanding_boundaries` rather than smoothed over — a submission that
    may not have landed must never read as one that did.
    """

    job_posting_id: str
    #: When the submit control was pressed, in UTC.
    submitted_at: datetime
    #: The label of the control that was pressed — what the candidate
    #: authorized, recorded as what was done.
    pressed_control: str
    #: Where the portal left the browser afterwards.
    final_url: str
    #: The opening of the page the portal answered with, so the candidate can
    #: see the confirmation (or the validation errors) in their own words.
    confirmation_excerpt: str = ""
    #: A PNG of the page the portal answered with. The candidate's proof of
    #: what was sent and what came back; None if the capture failed.
    screenshot_png: bytes | None = None
    #: Human-only checks the portal raised *after* the press — a challenge on
    #: submit. Non-empty means the application may not have been received and
    #: the candidate has to finish it themselves.
    outstanding_boundaries: list[ApplicationBoundaryOutput] = field(
        default_factory=list
    )

    @property
    def is_confirmed_sent(self) -> bool:
        """Whether the portal accepted the submission without asking for
        anything further.

        The one thing a caller must not infer from "no exception was
        raised": the press succeeded either way, and only the absence of a
        post-press boundary says the application actually went through.
        """
        return not self.outstanding_boundaries
