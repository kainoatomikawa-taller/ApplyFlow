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

The four ways a field ends up surfaced (`SurfaceReason`) are genuinely
different situations for a human: "the company wrote this question",
"ApplyFlow knows this field but your profile is silent", "this one is yours
to answer", and "your data doesn't fit this widget". Collapsing them into
one "couldn't fill it" would make the review step much harder to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.application.ports.browser_automation_port import FormField, FormFieldKind
from src.domain.entities.user_profile import UserProfile
from src.domain.services.ats_field_mapper import recognize_application_field
from src.domain.services.profile_field_values import resolve_profile_field
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    is_document_slot,
    requires_candidate_answer,
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

    One vocabulary covers both halves of the flow. The planner produces the
    first four from the form and the profile alone; the last two can only be
    discovered while executing the plan, since they need a document read.
    Keeping them in one enum means a review screen has a single set of
    reasons to explain, rather than two that mostly overlap.
    """

    #: Not one of the questions ApplyFlow claims to recognize — almost
    #: always a screening question the company wrote itself. The expected
    #: outcome for much of a real form, and not a defect.
    UNRECOGNIZED = "unrecognized"
    #: Recognized, but the candidate's profile holds nothing that answers
    #: it. Actionable: filling in the profile fixes it for every future
    #: application.
    NO_PROFILE_DATA = "no_profile_data"
    #: Recognized, and deliberately never autofilled — work authorization
    #: and EEO self-identification (see `REQUIRES_CANDIDATE_ANSWER`).
    REQUIRES_CANDIDATE_ANSWER = "requires_candidate_answer"
    #: Recognized, with data available, but the widget cannot take it — a
    #: checkbox where a value was expected, or a password field. Usually
    #: means the field was recognized wrongly, which is why it goes to a
    #: human instead of being forced.
    UNSUPPORTED_FIELD_KIND = "unsupported_field_kind"
    #: Recognized as the resume or cover letter, but no such document has
    #: been generated for this job yet. Generating one fixes it.
    DOCUMENT_NOT_GENERATED = "document_not_generated"
    #: The value is longer than the maximum length the portal declares for
    #: the field. Reported rather than truncated: a cover letter cut off
    #: mid-sentence still goes out under the candidate's name.
    VALUE_TOO_LONG = "value_too_long"


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
        slot = recognize_application_field(self._as_question(field), provider=provider)
        if slot is None:
            return self._surface(field, SurfaceReason.UNRECOGNIZED)

        if requires_candidate_answer(slot):
            return self._surface(
                field, SurfaceReason.REQUIRES_CANDIDATE_ANSWER, slot=slot
            )

        # Checked after recognition so a password field the recognizer
        # matched (a "Confirm email" style field mis-typed by the portal, or
        # a genuine account-creation box) is reported as recognized and
        # refused, rather than looking like an unknown field.
        if field.kind is FormFieldKind.PASSWORD:
            return self._surface(field, SurfaceReason.UNSUPPORTED_FIELD_KIND, slot=slot)

        if is_document_slot(slot):
            return self._plan_document_field(field, slot)

        return self._plan_value_field(field, slot, profile)

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
