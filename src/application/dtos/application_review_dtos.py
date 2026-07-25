"""DTOs — input/output contracts for reviewing a filled application and
sending it.

SENSITIVE: `AnswerApplicationFieldInput.value` is whatever the candidate
typed into a field on a real application form — which is routinely their
address, their salary expectation, or their EEO self-identification, since
answering EEO themselves is the *only* way it is ever answered. Never
logged. Log the review session id and the field id.

Sending is the candidate's act, and this is where that is enforced
--------------------------------------------------------------------
There is exactly one input type that can lead to a submission
(`SubmitApplicationFormInput`), it names one parked review session, and it
carries the candidate's confirmation of every sensitive value ApplyFlow
filled. Nothing constructs one on a schedule, from a queue, or as a
follow-on step of an autofill pass: the only caller is the authenticated
route the candidate hits when they press Submit. "Nothing is submitted
unattended" is that shape — a human instruction is a required input, not a
default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.application.dtos.application_autofill_dtos import ApplicationBoundaryOutput


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
