"""ReviewedAnswer — one question on an application form as it stands in the
candidate's review, plus who put that answer there.

Two things are tracked separately because they answer different questions, and
a review screen needs both:

- **`origin`** — who is responsible for this answer. "ApplyFlow filled this
  from your record" and "you typed this" are different claims, and a review UI
  that showed them identically would let a candidate submit an application
  without ever noticing which parts were written for them.
- **`decided_by_candidate`** — whether the candidate has explicitly settled
  this field. Only load-bearing for sensitive ones, where it is the gate
  before anything is handed over (see `ApplicationReview`).

Why every sensitive field starts undecided
------------------------------------------
Not only the ones ApplyFlow filled. A legal attestation it filled needs
confirming (the value came from the candidate's record, but asserting it to
*this* employer is theirs to make); an EEO question is never filled at all and
is theirs to answer or decline per application; and a sensitive field it could
not answer still needs them to say what goes in it. All three are "we are not
sending this until you have looked at it", so all three start `PENDING` and
none can be cleared by anything except a candidate's action.

Declining is a real answer
--------------------------
`AnswerOrigin.DECLINED` is how "leave this blank, deliberately" is recorded —
distinct from an empty value nobody has touched. Without it, the only way past
an EEO question would be to answer it, which is exactly the coercion
"voluntary" is supposed to rule out.

SENSITIVE: `value` holds whatever went onto (or is going onto) a real
application — a name, an address, a work-authorization declaration. Never log
one; log the `key` and the `slot`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    FieldSensitivity,
)


class AnswerOrigin(StrEnum):
    """Who is responsible for the answer currently in this field."""

    #: Nobody has answered it. ApplyFlow left it alone and the candidate has
    #: not filled it in — `explanation` says why it was left.
    UNANSWERED = "unanswered"
    #: ApplyFlow wrote it, from the candidate's own stored record.
    AUTOFILLED = "autofilled"
    #: The candidate wrote or changed it in the review.
    CANDIDATE = "candidate"
    #: The candidate deliberately left it blank.
    DECLINED = "declined"


@dataclass(frozen=True)
class ReviewedAnswer:
    """One form question, its current answer, and how settled that answer is."""

    #: Stable address for this answer within its review — assigned in page
    #: order when the review is opened. Opaque: it identifies a question in
    #: one review, and means nothing outside it.
    key: str
    #: The label the portal showed, so the candidate recognizes the field.
    label: str
    #: The widget the portal used (a `FormFieldKind` value), so a review UI
    #: can render an input that matches — a textarea for a long answer, a
    #: choice for a select.
    widget_kind: str
    value: str = ""
    #: The question ApplyFlow recognized this as, or None. Present even when
    #: unanswered: "we know this is the visa question and left it to you" is
    #: not the same message as "we have no idea what this field is".
    slot: ApplicationFieldSlot | None = None
    #: The sensitivity category, or None for an ordinary field. Carried
    #: rather than re-derived from `slot` so an answer's flagging survives
    #: storage and cannot be lost by a reader that forgot to look it up.
    sensitivity: FieldSensitivity | None = None
    required: bool = False
    origin: AnswerOrigin = AnswerOrigin.UNANSWERED
    #: Whether the candidate has explicitly settled this field — confirmed
    #: the value, changed it, or declined it.
    decided_by_candidate: bool = False
    #: Why ApplyFlow left this field alone, or what the portal said about the
    #: value. Written for the candidate to read.
    explanation: str = ""

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise InvalidValueError("ReviewedAnswer requires a non-empty key.")
        if not isinstance(self.origin, AnswerOrigin):
            raise InvalidValueError("ReviewedAnswer requires a valid AnswerOrigin.")
        if self.slot is not None and not isinstance(self.slot, ApplicationFieldSlot):
            raise InvalidValueError(
                "ReviewedAnswer.slot must be an ApplicationFieldSlot or None."
            )
        if self.sensitivity is not None and not isinstance(
            self.sensitivity, FieldSensitivity
        ):
            raise InvalidValueError(
                "ReviewedAnswer.sensitivity must be a FieldSensitivity or None."
            )
        if self.origin is AnswerOrigin.DECLINED and self.value:
            raise InvalidValueError(
                "A declined answer cannot carry a value — declining means "
                "leaving the field deliberately blank."
            )

    # ---- What a review screen asks ------------------------------------------

    @property
    def is_sensitive(self) -> bool:
        return self.sensitivity is not None

    @property
    def is_legal_attestation(self) -> bool:
        return self.sensitivity is FieldSensitivity.LEGAL_ATTESTATION

    @property
    def is_voluntary_self_id(self) -> bool:
        return self.sensitivity is FieldSensitivity.VOLUNTARY_SELF_ID

    @property
    def is_answered(self) -> bool:
        """Whether this field has an answer — including a deliberate blank.

        Declining counts: the candidate has said what should happen to this
        field, which is what "answered" has to mean if declining is to be a
        real option rather than a way of getting stuck.
        """
        return bool(self.value) or self.origin is AnswerOrigin.DECLINED

    @property
    def needs_candidate_decision(self) -> bool:
        """Whether this field still waits on the candidate before anything is
        handed over. True for every sensitive field they have not settled."""
        return self.is_sensitive and not self.decided_by_candidate

    @property
    def was_autofilled(self) -> bool:
        return self.origin is AnswerOrigin.AUTOFILLED

    # ---- The candidate's three moves ----------------------------------------

    def answered(self, value: str) -> ReviewedAnswer:
        """The candidate's own answer, replacing whatever was there.

        Settles the field: typing a value into a legal declaration *is* the
        explicit decision that declaration needs, so no separate confirmation
        is asked for afterwards.
        """
        cleaned = value.strip()
        if not cleaned:
            # An emptied field is not the same as a declined one, but it is
            # certainly not an answer — route it through `declined` so the two
            # states cannot blur into "blank, origin: candidate".
            return self.declined()
        return replace(
            self,
            value=cleaned,
            origin=AnswerOrigin.CANDIDATE,
            decided_by_candidate=True,
        )

    def confirmed(self) -> ReviewedAnswer:
        """The candidate approves the answer as it stands, unchanged.

        The path for an autofilled legal attestation: the value is right and
        they are willing to assert it to this employer.
        """
        if not self.is_answered:
            raise InvalidValueError(
                f"There is nothing to confirm on '{self.label or self.key}' — "
                "it has no answer yet."
            )
        return replace(self, decided_by_candidate=True)

    def declined(self) -> ReviewedAnswer:
        """The candidate deliberately leaves this field blank."""
        return replace(
            self,
            value="",
            origin=AnswerOrigin.DECLINED,
            decided_by_candidate=True,
        )
