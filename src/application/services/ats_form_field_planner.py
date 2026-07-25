"""AtsFormFieldPlanner — turns the fields a browser session read off an
application form into a decision per field: fill it with this, attach this
document to it, or hand it to a human.

Where this sits
---------------
Between two things that must not know about each other. The browser harness
(`BrowserSessionPort`) knows widgets and handles and nothing about
candidates; the domain recognizer and value resolver know candidates and
questions and nothing about browsers. This is the translation, and it does
no I/O at all — same inputs, same plan, every time — so the whole mapping
decision is testable without a browser and without a database.

Planning is deliberately separated from executing for a second reason: a
plan is reviewable. A future "show me what you would fill in before you
touch the form" screen needs exactly this and nothing more.

Every field gets a disposition — nothing is skipped silently
-----------------------------------------------------------
`plan()` returns one `PlannedField` per field it was given, in the order it
was given them. There is no filtering step, because a field the planner
dropped is a field nobody ever hears about again: the acceptance rule for
this work is that unmapped fields are *surfaced*, not guessed — and not
quietly discarded either, which is the same failure with better optics. A
field ApplyFlow cannot answer comes back as `SURFACE` carrying the reason
why, and the reason is what a review UI shows the candidate.

The ways a field ends up surfaced (`SurfaceReason`) are genuinely different
situations for a human: "the company wrote this question", "ApplyFlow knows
this field but your profile is silent", "this one is yours to answer", "your
data doesn't fit this widget". Collapsing them into one "couldn't fill it"
would make the review step much harder to act on.

A signature field is refused before anything else
-------------------------------------------------
The first check in `_plan_field` is `is_signature_field`, and it comes before
recognition on purpose. The usual shape of a signature on an ATS form is a
plain text input labelled "Signature (type your full name)" — a label the
recognizer reads as a request for the candidate's name, which it can answer.
Signing for someone is not an autofill decision, so the field never reaches
the rules that would fill it.

Sensitive fields take their own path
------------------------------------
Work authorization, sponsorship, citizenship, visa, and EEO self-ID are
routed to `decide_sensitive_field` before either ordinary path, and no rule
about them lives here — this service only translates that verdict into a
plan. Two consequences worth knowing:

- A sensitive slot can never reach `resolve_profile_field`. That function
  refuses them as well, so the policy holds even if this routing is later
  changed by someone who hasn't read it.
- Every `PlannedField` reports `is_sensitive`, `sensitivity`, and
  `requires_confirmation` as *derived* properties of its slot rather than as
  fields someone has to remember to set. A sensitive field cannot be
  constructed here and reported as ordinary, which is what makes the review
  step's flagging reliable rather than conventional.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.application.ports.browser_automation_port import FormField, FormFieldKind
from src.domain.entities.user_profile import UserProfile
from src.domain.services.application_boundary_detector import is_signature_field
from src.domain.services.ats_field_mapper import recognize_application_field
from src.domain.services.human_only_field_policy import HumanOnlyFieldPolicy
from src.domain.services.profile_field_values import resolve_profile_field
from src.domain.services.sensitive_field_policy import (
    SensitiveFieldRefusal,
    decide_sensitive_field,
)
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    FieldSensitivity,
    is_document_slot,
    is_sensitive_slot,
    sensitivity_of,
)
from src.domain.value_objects.ats_form_question import AtsFormQuestion
from src.domain.value_objects.ats_provider import AtsProvider
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind

#: Widget kinds a text value can be written into. `SELECT` is included
#: because a value either names one of its options exactly or is refused by
#: the harness (see `RejectedFieldValueError`) — country and state dropdowns
#: are filled this way routinely and safely.
#:
#: `CHECKBOX` and `RADIO` are excluded on purpose. Writing a profile string
#: into a tick box means asking the harness to interpret "Austin, TX" as
#: yes-or-no; the honest answer is that a checkbox standing where a text
#: field was expected is a field ApplyFlow has misread, so it goes to a
#: human. `PASSWORD` is excluded because nothing here may ever invent a
#: credential, and `FILE` because it takes an attachment, not a value.
_TEXT_VALUE_KINDS: frozenset[FormFieldKind] = frozenset(
    {
        FormFieldKind.TEXT,
        FormFieldKind.EMAIL,
        FormFieldKind.PHONE,
        FormFieldKind.URL,
        FormFieldKind.NUMBER,
        FormFieldKind.DATE,
        FormFieldKind.TEXTAREA,
        FormFieldKind.SELECT,
    }
)

#: Widget kinds a document's text can be pasted into when the form offers no
#: upload — Greenhouse's "or paste your resume" textarea.
_DOCUMENT_TEXT_KINDS: frozenset[FormFieldKind] = frozenset(
    {FormFieldKind.TEXTAREA, FormFieldKind.TEXT}
)

#: Widget kinds a sensitive legal answer may be written into.
#:
#: `RADIO` is here and not in `_TEXT_VALUE_KINDS` because a Yes/No radio group
#: is how portals most often ask the authorization and sponsorship questions,
#: and it is safe for exactly this shape of answer: the harness selects a
#: radio by its own option label, so "Yes" either names an option or is
#: refused.
#:
#: `CHECKBOX` is excluded, and that exclusion is the point. A tick box is
#: unlabelled as to polarity — "I require sponsorship" and "I do not require
#: sponsorship" are both real labels, and a harness told to tick for "Yes"
#: cannot tell them apart. Getting that backwards inverts a legal declaration,
#: so these go to a human instead.
_SENSITIVE_ANSWER_KINDS: frozenset[FormFieldKind] = frozenset(
    {
        FormFieldKind.TEXT,
        FormFieldKind.TEXTAREA,
        FormFieldKind.SELECT,
        FormFieldKind.RADIO,
    }
)

#: Which stored snapshot answers each document slot.
_SLOT_DOCUMENTS: dict[ApplicationFieldSlot, GeneratedDocumentKind] = {
    ApplicationFieldSlot.RESUME: GeneratedDocumentKind.TAILORED_RESUME,
    ApplicationFieldSlot.COVER_LETTER: GeneratedDocumentKind.COVER_LETTER,
}


class FieldDisposition(StrEnum):
    """What the executing caller should do with one field."""

    #: Write `value` into it.
    FILL = "fill"
    #: Attach the document named by `document_kind` as a file.
    ATTACH_DOCUMENT = "attach_document"
    #: Write the text of the document named by `document_kind` into it.
    FILL_DOCUMENT_TEXT = "fill_document_text"
    #: Leave it alone and report it to a human — see `SurfaceReason`.
    SURFACE = "surface"


class SurfaceReason(StrEnum):
    """Why a field was left for a human.

    One vocabulary covers both halves of the flow. Most reasons are produced
    by the planner from the form and the profile alone; the last two
    (`DOCUMENT_NOT_GENERATED`, `VALUE_TOO_LONG`) can only be discovered while
    executing the plan, since they need a document read. Keeping them in one
    enum means a review screen has a single set of reasons to explain, rather
    than two that mostly overlap.
    """

    #: Not one of the questions ApplyFlow claims to recognize — almost
    #: always a screening question the company wrote itself. The expected
    #: outcome for much of a real form, and not a defect.
    UNRECOGNIZED = "unrecognized"
    #: Recognized, but the candidate's profile holds nothing that answers
    #: it. Actionable: filling in the profile fixes it for every future
    #: application.
    NO_PROFILE_DATA = "no_profile_data"
    #: Recognized, and deliberately never autofilled: EEO self-identification
    #: (see `REQUIRES_CANDIDATE_ANSWER`). Not a gap in the profile and not
    #: something filling one in would fix — the candidate decides this per
    #: application.
    REQUIRES_CANDIDATE_ANSWER = "requires_candidate_answer"
    #: A legal question whose answer is on file but was not stated by the
    #: candidate themselves (see `WorkAuthorization.ATTESTING_SOURCES`).
    #: Confirming it on the profile turns it into an answer ApplyFlow may
    #: give.
    SENSITIVE_DATA_NOT_ATTESTED = "sensitive_data_not_attested"
    #: A legal question the stored record does not settle exactly — a visa
    #: holder asked about future sponsorship, an "other" status. Answering
    #: approximately is the one thing these fields must never do.
    SENSITIVE_ANSWER_NOT_DERIVABLE = "sensitive_answer_not_derivable"
    #: Recognized, with data available, but ApplyFlow will not write it:
    #: either the widget cannot take the value (a checkbox where a value was
    #: expected — usually means the field was recognized wrongly, which is why
    #: it goes to a human instead of being forced), or the field is one only
    #: the candidate may ever fill — a password, a signature, a challenge
    #: answer (see `HumanOnlyFieldPolicy`). The second case is not a defect in
    #: the reading and never becomes fillable; the boundary is explained to
    #: the candidate through the hand-off flow (`PortalHandoff`), not here.
    UNSUPPORTED_FIELD_KIND = "unsupported_field_kind"
    #: Recognized as the resume or cover letter, but no such document has
    #: been generated for this job yet. Generating one fixes it.
    DOCUMENT_NOT_GENERATED = "document_not_generated"
    #: The value is longer than the maximum length the portal declares for
    #: the field. Reported rather than truncated: a cover letter cut off
    #: mid-sentence still goes out under the candidate's name.
    VALUE_TOO_LONG = "value_too_long"
    #: The field is where the candidate signs. Never filled, by anything,
    #: under any circumstances — see `is_signature_field`.
    REQUIRES_CANDIDATE_SIGNATURE = "requires_candidate_signature"


#: The domain's refusal reasons, translated into the review vocabulary.
#:
#: Absent data maps onto the same `NO_PROFILE_DATA` an ordinary field would
#: report, because the remedy is identical and a reviewer should not have to
#: learn two words for "your profile doesn't say". The other three keep their
#: own reasons — they call for confirming, answering, or nothing at all, which
#: are different asks.
_REFUSAL_REASONS: dict[SensitiveFieldRefusal, SurfaceReason] = {
    SensitiveFieldRefusal.CANDIDATE_CHOICE_ONLY: (
        SurfaceReason.REQUIRES_CANDIDATE_ANSWER
    ),
    SensitiveFieldRefusal.NOT_ON_FILE: SurfaceReason.NO_PROFILE_DATA,
    SensitiveFieldRefusal.NOT_STATED: SurfaceReason.NO_PROFILE_DATA,
    SensitiveFieldRefusal.NOT_CANDIDATE_ATTESTED: (
        SurfaceReason.SENSITIVE_DATA_NOT_ATTESTED
    ),
    SensitiveFieldRefusal.NOT_DERIVABLE: (SurfaceReason.SENSITIVE_ANSWER_NOT_DERIVABLE),
}


@dataclass(frozen=True)
class PlannedField:
    """One form field plus the decision made about it."""

    field: FormField
    disposition: FieldDisposition
    #: The question this field was recognized as, or None when it wasn't
    #: recognized at all. Present even on a surfaced field, so a reviewer
    #: can see that ApplyFlow knew what the field was and still declined.
    slot: ApplicationFieldSlot | None = None
    #: The text to write, set only when `disposition` is FILL.
    value: str | None = None
    #: Which stored document to use, set only for the two document
    #: dispositions.
    document_kind: GeneratedDocumentKind | None = None
    #: Whether `value` was derived rather than read verbatim (see
    #: `ProfileFieldValue`).
    is_derived: bool = False
    #: Set only when `disposition` is SURFACE.
    surface_reason: SurfaceReason | None = None

    @property
    def sensitivity(self) -> FieldSensitivity | None:
        """This field's sensitivity category, or None if it isn't sensitive.

        Derived from the slot rather than stored, so it cannot be forgotten
        on a code path that constructs a `PlannedField` — a sensitive field
        reported as ordinary is precisely the flagging failure this ticket
        exists to prevent.
        """
        return sensitivity_of(self.slot) if self.slot is not None else None

    @property
    def is_sensitive(self) -> bool:
        return self.sensitivity is not None

    @property
    def requires_confirmation(self) -> bool:
        """Whether a human must confirm this value before it is submitted.

        True for a sensitive field ApplyFlow filled. A legal declaration
        derived from stored data is still the candidate's statement to make,
        and the jurisdiction gap in `decide_sensitive_field` is caught here or
        nowhere.
        """
        return self.is_sensitive and self.disposition is FieldDisposition.FILL


class AtsFormFieldPlanner:
    """Maps read form fields onto profile and document data."""

    def plan(
        self,
        fields: tuple[FormField, ...],
        *,
        provider: AtsProvider,
        profile: UserProfile,
    ) -> tuple[PlannedField, ...]:
        """Decide what to do with every field in `fields`, in order.

        `provider` is one of the three platforms field mapping covers;
        resolving an apply URL to one is `identify_ats_board`'s job, and a
        URL that resolves to nothing never reaches here.
        """
        return tuple(
            self._plan_field(field, provider=provider, profile=profile)
            for field in fields
        )

    def _plan_field(
        self, field: FormField, *, provider: AtsProvider, profile: UserProfile
    ) -> PlannedField:
        # Before recognition, and before anything else, because the most
        # common signature field on an ATS form is a text input labelled
        # "Signature (type your full name)" — which the recognizer reads as
        # the candidate's name and would answer with it. Typing a person's
        # name into a signature box is signing for them.
        if is_signature_field(field.label):
            return self._surface(field, SurfaceReason.REQUIRES_CANDIDATE_SIGNATURE)

        slot = recognize_application_field(self._as_question(field), provider=provider)
        if slot is None:
            return self._surface(field, SurfaceReason.UNRECOGNIZED)

        # Checked after recognition so a field the recognizer matched but
        # ApplyFlow may never answer (a "Confirm email" style field mis-typed
        # by the portal, a genuine account-creation box, a signature line
        # named like a full-name field) is reported as recognized and
        # refused, rather than looking like an unknown field.
        #
        # Asks the domain policy rather than reading `field.human_only_boundary`
        # alone: the tag is applied by field discovery, and this guard has to
        # hold for a `FormField` from any source. It is also what keeps the
        # harness's own refusal (`HumanOnlyFieldError`) unreachable from here —
        # that error is raised at the moment of typing and is not caught
        # per-field, so a pass that reached it would lose the report for every
        # field it had already filled correctly.
        if _is_human_only(field):
            return self._surface(field, SurfaceReason.UNSUPPORTED_FIELD_KIND, slot=slot)

        # Before the ordinary paths, so a sensitive slot can never reach the
        # generic profile resolver — the domain refuses it there too, and
        # this ordering is what makes that second guard unreachable rather
        # than load-bearing.
        if is_sensitive_slot(slot):
            return self._plan_sensitive_field(field, slot, profile)

        if is_document_slot(slot):
            return self._plan_document_field(field, slot)

        return self._plan_value_field(field, slot, profile)

    def _plan_sensitive_field(
        self, field: FormField, slot: ApplicationFieldSlot, profile: UserProfile
    ) -> PlannedField:
        """Apply the sensitive-field policy: fill an exact legal answer, or
        surface the field with the reason it cannot be answered.

        The whole decision belongs to `decide_sensitive_field` — this method
        only translates its verdict into a plan, and deliberately contains no
        rule of its own. EEO is refused inside that function before any data
        is read, so there is no branch here that could answer it.
        """
        decision = decide_sensitive_field(slot, profile=profile)
        if decision.refusal is not None:
            return self._surface(field, _REFUSAL_REASONS[decision.refusal], slot=slot)

        if field.kind not in _SENSITIVE_ANSWER_KINDS:
            return self._surface(field, SurfaceReason.UNSUPPORTED_FIELD_KIND, slot=slot)

        return PlannedField(
            field=field,
            disposition=FieldDisposition.FILL,
            slot=slot,
            value=decision.answer,
        )

    def _plan_document_field(
        self, field: FormField, slot: ApplicationFieldSlot
    ) -> PlannedField:
        """Decide how this form wants the resume or cover letter.

        Whether the document arrives as a PDF upload or as pasted text is
        the form's choice, not the slot's, so both paths exist and the
        widget picks between them. Whether the document actually *exists*
        is left to the executing caller — that needs a repository read,
        which this service does not do.
        """
        document_kind = _SLOT_DOCUMENTS[slot]
        if field.kind is FormFieldKind.FILE:
            return PlannedField(
                field=field,
                disposition=FieldDisposition.ATTACH_DOCUMENT,
                slot=slot,
                document_kind=document_kind,
            )
        if field.kind in _DOCUMENT_TEXT_KINDS:
            return PlannedField(
                field=field,
                disposition=FieldDisposition.FILL_DOCUMENT_TEXT,
                slot=slot,
                document_kind=document_kind,
            )
        # A "cover letter" checkbox ("I'd like to include one") or select is
        # asking something else entirely — a preference, not the document.
        return self._surface(field, SurfaceReason.UNSUPPORTED_FIELD_KIND, slot=slot)

    def _plan_value_field(
        self, field: FormField, slot: ApplicationFieldSlot, profile: UserProfile
    ) -> PlannedField:
        """Answer a recognized field from the profile, or surface it.

        The profile is consulted before the widget is checked so that "your
        profile has no phone number" is reported in preference to "a phone
        number won't fit this widget" — the first is the thing a candidate
        can actually act on.
        """
        resolved = resolve_profile_field(profile, slot)
        if resolved is None:
            return self._surface(field, SurfaceReason.NO_PROFILE_DATA, slot=slot)

        if field.kind not in _TEXT_VALUE_KINDS:
            return self._surface(field, SurfaceReason.UNSUPPORTED_FIELD_KIND, slot=slot)

        return PlannedField(
            field=field,
            disposition=FieldDisposition.FILL,
            slot=slot,
            value=resolved.text,
            is_derived=resolved.is_derived,
        )

    @staticmethod
    def _as_question(field: FormField) -> AtsFormQuestion:
        """Narrow a live form field to the four signals the recognizer reads
        (see `AtsFormQuestion` on why it is not handed the whole thing)."""
        return AtsFormQuestion(
            label=field.label,
            control_name=field.name,
            element_id=field.attributes.get("id", ""),
            autocomplete=field.attributes.get("autocomplete", ""),
        )

    @staticmethod
    def _surface(
        field: FormField,
        reason: SurfaceReason,
        *,
        slot: ApplicationFieldSlot | None = None,
    ) -> PlannedField:
        return PlannedField(
            field=field,
            disposition=FieldDisposition.SURFACE,
            slot=slot,
            surface_reason=reason,
        )


def _is_human_only(field: FormField) -> bool:
    """Whether this field is one only the candidate may ever fill.

    Prefers the boundary field discovery already assigned, and falls back to
    re-deriving it from the same domain policy, so the answer does not depend
    on which layer built the `FormField`.
    """
    if field.human_only_boundary is not None:
        return True
    return (
        HumanOnlyFieldPolicy.boundary_for(
            kind_name=field.kind.value,
            label=field.label,
            name=field.name,
            attribute_values=(*field.attributes.values(), field.placeholder),
        )
        is not None
    )
