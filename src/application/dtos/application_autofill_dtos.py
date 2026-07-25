"""DTOs — input/output contracts for autofilling an ATS application form.

SENSITIVE: `AutofilledFieldOutput.value` carries what was written onto a real
application form — the candidate's name, email, phone, address, and, on the
legal-attestation fields, their work-authorization answers. The output exists
to be reviewed by the candidate, so it necessarily contains all of this; it
must never be logged. Log the `job_posting_id` and the outcome counts instead.

Flagging sensitive fields is part of the contract
------------------------------------------------
Each field carries `is_sensitive`, `sensitivity`, and
`requires_confirmation`, so a review UI never has to infer sensitivity by
pattern-matching slot names — a UI that got that inference wrong would render
a visa declaration as an ordinary text box. `sensitive_fields` and
`fields_awaiting_confirmation` are the two lists a review screen needs:
what to flag, and what must be approved before anything is submitted.

The output is one list, not two
------------------------------
Every field the form presented appears in `fields`, in the order it appears
on the page, whether it was filled or not. A caller wanting only the ones
needing attention reads `fields_needing_review`; a caller rendering a review
screen wants the whole form in order, because a list of five orphaned
questions with no surrounding context is much harder to answer than the form
they came from. Two independent lists would also let the two drift.

This report is always "what is now typed into the form", never "what was
sent". Sending is a separate act, requested separately by the candidate
(`SubmitApplicationFormInput`) and reported separately
(`ApplicationSubmissionOutput`); nothing in an autofill pass submits
anything.

Hand-offs are part of the report
--------------------------------
`boundaries` carries every human-only check found on the page — a login
wall, a CAPTCHA, a signature request. It is not an error channel: a report
with a CAPTCHA on it still lists every field that was filled, because the
filling is still worth having. What it changes is what happens next, and
`review_session_id` is the honest signal for that — when a boundary stopped
the pass, there is no parked session and no submission to make, so the id
is None and the instruction on the boundary is what the candidate acts on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True)
class AutofillApplicationFormInput:
    """Autofill the form at one posting's apply URL from a candidate's data."""

    user_id: str
    job_posting_id: str


class FieldAutofillOutcome(StrEnum):
    """What actually happened to one field."""

    #: A value was written into it.
    FILLED = "filled"
    #: A generated document was attached to it as a file.
    ATTACHED = "attached"
    #: Left untouched, for a human to answer — `reason` says why (a
    #: `SurfaceReason`, or a document that was never generated).
    SURFACED = "surfaced"
    #: The form itself refused the value, and said which values it accepts
    #: (see `RejectedFieldValueError`). Distinct from SURFACED because the
    #: mapping was right and the *value* was wrong — a state dropdown
    #: spelling "California" as "CA", say — so the fix is a different value,
    #: not a human answering a question ApplyFlow couldn't.
    NOT_ACCEPTED = "not_accepted"
    #: The field was addressed correctly but would not take input at all
    #: (obscured, detached mid-write). An infrastructure failure against
    #: this one field; the rest of the form still filled.
    FAILED = "failed"


#: Outcomes that mean something was actually written onto the form. Public
#: because it is part of the contract, not an implementation detail: a caller
#: deciding whether a value reached the form must use the same definition
#: `was_applied` does, rather than re-listing the outcomes and drifting.
APPLIED_OUTCOMES: frozenset[FieldAutofillOutcome] = frozenset(
    {FieldAutofillOutcome.FILLED, FieldAutofillOutcome.ATTACHED}
)


@dataclass(frozen=True)
class AutofilledFieldOutput:
    """One field on the form and what became of it."""

    #: Opaque id for this field within its review session — what a review
    #: screen sends back to answer the field or to confirm its value. It is
    #: the browser handle, which means it stops working the moment the form
    #: is re-read or the page moves underneath the snapshot; that is the
    #: intended behavior, since an id that outlived the snapshot would let a
    #: confirmation approve a value on a field that has since changed.
    field_id: str
    #: The field's label as the page presented it — what a reviewer will
    #: recognize. May be empty for a field a portal labels only visually.
    label: str
    #: The widget kind (a `FormFieldKind` value), so a review UI can render
    #: an appropriate input for a field the candidate still has to answer.
    kind: str
    #: Whether the portal marked the field required. Only as trustworthy as
    #: the portal's markup (see `FormField.required`), but a required field
    #: that is still unanswered is the one a reviewer must not miss.
    required: bool
    outcome: str
    #: The `ApplicationFieldSlot` this field was recognized as, or None if it
    #: wasn't recognized. Set even on a surfaced field — "we know this is
    #: the visa question and are leaving it to you" is a different message
    #: from "we have no idea what this field is".
    slot: str | None = None
    #: What was written, for FILLED; the attached filename, for ATTACHED;
    #: the refused value, for NOT_ACCEPTED. None when nothing was written.
    #: For a pasted document this is the document's text, which is the
    #: content that went onto the form.
    value: str | None = None
    #: Whether `value` was derived from stored facts rather than read
    #: verbatim (see `ProfileFieldValue`) — where a reviewer should look
    #: first among the fields that *were* filled.
    is_derived: bool = False
    #: A machine-readable code for the outcome: a `SurfaceReason` value, or
    #: a document/limit code for the cases that arise only during execution.
    reason: str | None = None
    #: Human-readable detail — the options a select would have accepted, the
    #: reason a write failed. Safe to show a candidate.
    detail: str | None = None
    #: Whether this field carries sensitive data. A review UI MUST flag these
    #: distinctly; see `sensitivity` for which of the two kinds it is.
    is_sensitive: bool = False
    #: The `FieldSensitivity` category when sensitive, else None.
    #: `legal_attestation` is a declaration the candidate is accountable for
    #: (work authorization, sponsorship, citizenship, visa);
    #: `voluntary_self_id` is EEO data, which is never autofilled and is the
    #: candidate's choice on every individual application.
    sensitivity: str | None = None
    #: Whether a human must confirm this value before the form is submitted.
    #: True for a sensitive field ApplyFlow filled: the value came from the
    #: candidate's own attested record, but asserting it to *this* employer is
    #: still theirs to approve.
    requires_confirmation: bool = False
    #: Whether the candidate answered this field themselves in the review
    #: step. Such a value is already their own statement, so it never also
    #: needs confirming — the confirmation gate exists for values ApplyFlow
    #: derived from stored data, not for words the candidate just typed.
    answered_by_candidate: bool = False

    @property
    def was_applied(self) -> bool:
        """Whether this field was actually written onto the form."""
        return self.outcome in APPLIED_OUTCOMES


@dataclass(frozen=True)
class ApplicationBoundaryOutput:
    """One human-only check found on the page (see `ApplicationBoundary`).

    Flattened out of the domain value object rather than passed through, so
    a caller never has to import a domain type to render a hand-off — and
    `instruction` travels with the finding, because a hand-off that says
    what was found but not what to do about it just strands the candidate.
    """

    #: An `ApplicationBoundaryKind` value: login, captcha, signature.
    kind: str
    #: What was actually seen, in terms the candidate can check.
    evidence: str
    #: What the candidate should do about it.
    instruction: str
    #: Whether this boundary meant the form was not filled at all.
    stopped_autofill: bool
    #: Whether this boundary puts submission beyond ApplyFlow's reach.
    blocks_submission: bool


@dataclass(frozen=True)
class ApplicationAutofillOutput:
    """The result of one autofill pass over one application form."""

    job_posting_id: str
    #: The URL the session actually ended on, which may differ from the
    #: posting's `apply_url` — portals routinely redirect apply links.
    apply_url: str
    #: Which of the three supported platforms this form was read as.
    ats_provider: str
    #: Every field the form presented, in page order.
    fields: list[AutofilledFieldOutput] = field(default_factory=list)
    #: A PNG of the filled form, the evidence a reviewer checks the report
    #: against. None when the capture itself failed — which loses proof, not
    #: work, so it does not fail the pass.
    screenshot_png: bytes | None = None
    #: Every human-only check found on the page, in a fixed order. Empty is
    #: the ordinary case.
    boundaries: list[ApplicationBoundaryOutput] = field(default_factory=list)
    #: The parked review session this report belongs to — what the candidate
    #: answers remaining fields through and submits through. None when there
    #: is nothing to submit: a boundary stopped the pass before any field was
    #: filled, so no session was left open.
    review_session_id: str | None = None
    #: When the parked session will be closed if the candidate does not
    #: finish. None when there is no session.
    review_expires_at: datetime | None = None

    @property
    def applied_fields(self) -> list[AutofilledFieldOutput]:
        """The fields ApplyFlow actually filled or attached."""
        return [item for item in self.fields if item.was_applied]

    @property
    def fields_needing_review(self) -> list[AutofilledFieldOutput]:
        """Every field still waiting on a human, in page order.

        This is the "unmapped fields are surfaced, not guessed" contract in
        its readable form: whatever ApplyFlow could not answer is here, with
        a reason, rather than filled with something plausible.
        """
        return [item for item in self.fields if not item.was_applied]

    @property
    def unanswered_required_fields(self) -> list[AutofilledFieldOutput]:
        """The subset of `fields_needing_review` the portal marked required
        — the fields that will block submission."""
        return [item for item in self.fields_needing_review if item.required]

    @property
    def sensitive_fields(self) -> list[AutofilledFieldOutput]:
        """Every sensitive field on the form, filled or not, in page order.

        What a review screen flags distinctly. Filled or unfilled both belong
        here: an autofilled work-authorization answer needs confirming, and an
        untouched EEO question needs the candidate to decide — a UI that only
        highlighted one of those would hide half the sensitive surface.
        """
        return [item for item in self.fields if item.is_sensitive]

    @property
    def fields_awaiting_confirmation(self) -> list[AutofilledFieldOutput]:
        """Sensitive values ApplyFlow filled that a human has not approved.

        The gate before submission: these are legal declarations written from
        the candidate's stored record, and nothing should go out until they
        have looked at them.
        """
        return [item for item in self.fields if item.requires_confirmation]

    @property
    def requires_handoff(self) -> bool:
        """Whether the candidate has to finish this application themselves."""
        return bool(self.boundaries)

    @property
    def can_be_submitted_here(self) -> bool:
        """Whether submitting through ApplyFlow is available at all.

        False when there is no parked session (a boundary stopped the pass)
        or when a boundary on the page puts submission out of reach. Says
        nothing about whether the application is *ready* — the confirmation
        and completeness gates live in `SubmitApplicationForm`, which
        re-checks all of this against the live page rather than trusting a
        report a client may have been holding for ten minutes.
        """
        if self.review_session_id is None:
            return False
        return not any(boundary.blocks_submission for boundary in self.boundaries)
