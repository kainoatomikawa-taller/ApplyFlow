"""DTOs — input/output contracts for autofilling an ATS application form.

SENSITIVE: `AutofilledFieldOutput.value` carries what was written onto a real
application form — the candidate's name, email, phone, and address. The
output exists to be reviewed by the candidate, so it necessarily contains
their contact details; it must never be logged. Log the `job_posting_id` and
the outcome counts instead.

The output is one list, not two
------------------------------
Every field the form presented appears in `fields`, in the order it appears
on the page, whether it was filled or not. A caller wanting only the ones
needing attention reads `fields_needing_review`; a caller rendering a review
screen wants the whole form in order, because a list of five orphaned
questions with no surrounding context is much harder to answer than the form
they came from. Two independent lists would also let the two drift.

Nothing here can submit an application — the browser harness exposes no way
to (see `BrowserAutomationPort`), so this report is always "what is now
typed into the form", never "what was sent".
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


#: Outcomes that mean something was actually written onto the form.
_APPLIED_OUTCOMES = frozenset(
    {FieldAutofillOutcome.FILLED, FieldAutofillOutcome.ATTACHED}
)


@dataclass(frozen=True)
class AutofilledFieldOutput:
    """One field on the form and what became of it."""

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

    @property
    def was_applied(self) -> bool:
        """Whether this field was actually written onto the form."""
        return self.outcome in _APPLIED_OUTCOMES


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
