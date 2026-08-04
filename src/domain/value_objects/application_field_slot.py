"""ApplicationFieldSlot — the closed set of questions ApplyFlow claims to
recognize on an application form.

A slot is a *question*, not a widget and not a profile column. "Give us
your family name" is one slot whether the portal renders it as
`last_name`, `job_application[last_name]`, or a React input labelled
"Surname ✱"; and the resume slot is one slot whether the form takes a file
upload or a textarea. That separation is what keeps the recognizer (which
reads markup) independent of the value resolver (which reads the
candidate's record) and of the filler (which knows how to drive a widget).

Closed on purpose
-----------------
The enum is the coverage boundary. Field mapping is endless work — every
company adds its own screening questions — so what stops it from sprawling
is that a form field either matches a member here or is handed to a human
untouched. Nothing in this codebase invents a slot at runtime, and adding
one is a deliberate change with a value resolver and tests attached.

Members that no profile data can answer
---------------------------------------
`MIDDLE_NAME`, `PREFERRED_NAME`, and `ADDRESS_LINE_2` are here even though
`UserProfile` stores nothing that answers them. They earn their place by
being recognized and then *declined*: without them, a field labelled
"Preferred name" matches the generic name rule and gets the candidate's
legal name written into it. Recognizing a question ApplyFlow cannot answer
is how it gets surfaced instead of guessed.

Sensitive slots
---------------
Four slots carry the always-asked legal questions and one carries voluntary
EEO self-identification. They are classified by `FieldSensitivity` and
handled by their own domain service (`decide_sensitive_field`) rather than
by the ordinary profile resolver — see `SENSITIVE_SLOTS` below for why the
two categories are treated differently, and why neither can be answered
through the generic path.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class ApplicationFieldSlot(StrEnum):
    """One question an ATS application form can ask that ApplyFlow maps."""

    # ---- Identity ---------------------------------------------------------
    FULL_NAME = "full_name"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    #: Recognized so the generic name rule cannot claim them; never answered.
    MIDDLE_NAME = "middle_name"
    PREFERRED_NAME = "preferred_name"

    # ---- Contact ----------------------------------------------------------
    EMAIL = "email"
    PHONE = "phone"
    #: The single free-text "where are you based" field (Greenhouse's
    #: "Location (City)", Ashby's `_systemfield_location`), as opposed to the
    #: decomposed postal address below.
    LOCATION = "location"
    STREET_ADDRESS = "street_address"
    #: Recognized so the "address" rule cannot claim it; never answered.
    ADDRESS_LINE_2 = "address_line_2"
    CITY = "city"
    STATE_OR_REGION = "state_or_region"
    POSTAL_CODE = "postal_code"
    COUNTRY = "country"

    # ---- Links ------------------------------------------------------------
    LINKEDIN_URL = "linkedin_url"
    GITHUB_URL = "github_url"
    PORTFOLIO_URL = "portfolio_url"

    # ---- Current employment ----------------------------------------------
    CURRENT_COMPANY = "current_company"
    CURRENT_TITLE = "current_title"

    # ---- Education --------------------------------------------------------
    SCHOOL = "school"
    DEGREE = "degree"
    #: The majors, joined. Named for the label forms actually use; a form
    #: labelled "Major" maps here too (see `ats_field_mapper`).
    FIELD_OF_STUDY = "field_of_study"
    #: Separate from `FIELD_OF_STUDY` because a minor is a weaker claim than a
    #: major, and answering a "Minor" box with a major would overstate it.
    MINOR = "minor"
    EDUCATION_START_DATE = "education_start_date"
    EDUCATION_END_DATE = "education_end_date"

    # ---- Documents --------------------------------------------------------
    #: Answered from the stored `ApplicationDocument` snapshot for this job,
    #: never from the profile — see `DOCUMENT_SLOTS`.
    RESUME = "resume"
    COVER_LETTER = "cover_letter"

    # ---- Sensitive: the always-asked legal questions ----------------------
    # Split into one slot per question rather than one "work authorization"
    # catch-all, because each takes a *different* answer from the same stored
    # record and only an exact answer is acceptable on a legal form. Lumping
    # them together would leave nothing precise enough to fill: "are you
    # authorized?" and "will you need sponsorship?" can both be yes, both be
    # no, or disagree.
    WORK_AUTHORIZATION = "work_authorization"
    SPONSORSHIP_REQUIRED = "sponsorship_required"
    CITIZENSHIP_COUNTRY = "citizenship_country"
    VISA_TYPE = "visa_type"

    # ---- Sensitive: voluntary self-identification ------------------------
    EEO_SELF_IDENTIFICATION = "eeo_self_identification"


#: Slots answered from a generated document rather than from profile data.
#: The medium is the form's business, not the slot's: a resume field may be
#: a file input on one portal and a textarea on the next, and both are
#: `RESUME`.
DOCUMENT_SLOTS: frozenset[ApplicationFieldSlot] = frozenset(
    {ApplicationFieldSlot.RESUME, ApplicationFieldSlot.COVER_LETTER}
)


class FieldSensitivity(StrEnum):
    """Why a slot is sensitive, which decides how it may be answered.

    The two categories look similar — both are data an employer asks for and
    an employer must handle carefully — and they need opposite treatment, so
    the distinction is drawn in the domain rather than left to a caller's
    judgement.
    """

    #: A legal declaration the candidate is accountable for: work
    #: authorization, sponsorship, citizenship, visa. Backed by
    #: `WorkAuthorization`.
    #:
    #: These MUST be answered when the candidate's record answers them
    #: exactly. Leaving a required authorization question blank stalls the
    #: application; answering it approximately is a misstatement on a legal
    #: form. So the rule is exact-or-refuse, never approximate, and every
    #: filled answer is flagged for the candidate to confirm before anything
    #: is submitted (see `requires_confirmation` on the autofill report).
    LEGAL_ATTESTATION = "legal_attestation"

    #: Voluntary EEO self-identification: gender, race/ethnicity, veteran
    #: status, disability. Backed by `EeoSelfIdentification`.
    #:
    #: NEVER answered by ApplyFlow, under any circumstances — see
    #: `REQUIRES_CANDIDATE_ANSWER`.
    VOLUNTARY_SELF_ID = "voluntary_self_id"


#: Every sensitive slot and its category. Read-only so no caller can extend
#: the policy at runtime: which fields are sensitive is a domain decision,
#: reviewed with the code, never assembled by configuration.
#:
#: Membership here has teeth beyond labelling. A slot in this mapping cannot
#: be answered through `resolve_profile_field` at all (it refuses them
#: outright) — only `decide_sensitive_field` may, and it applies this
#: policy. That means a future contributor cannot accidentally route a visa
#: question through the ordinary path and have it quietly answered.
SENSITIVE_SLOTS: Mapping[ApplicationFieldSlot, FieldSensitivity] = MappingProxyType(
    {
        ApplicationFieldSlot.WORK_AUTHORIZATION: FieldSensitivity.LEGAL_ATTESTATION,
        ApplicationFieldSlot.SPONSORSHIP_REQUIRED: FieldSensitivity.LEGAL_ATTESTATION,
        ApplicationFieldSlot.CITIZENSHIP_COUNTRY: FieldSensitivity.LEGAL_ATTESTATION,
        ApplicationFieldSlot.VISA_TYPE: FieldSensitivity.LEGAL_ATTESTATION,
        ApplicationFieldSlot.EEO_SELF_IDENTIFICATION: (
            FieldSensitivity.VOLUNTARY_SELF_ID
        ),
    }
)


#: Slots ApplyFlow will never answer, whatever is on file.
#:
#: EEO self-identification only, and the reasoning is specific to it rather
#: than to sensitivity in general. Disclosing gender, race, veteran status,
#: or disability is voluntary by law and is a decision a candidate makes
#: **per application** — the same person may reasonably answer for one
#: employer and decline for the next. An autofill that carried last week's
#: answer forward would quietly convert one disclosure into a standing one,
#: which is the opposite of what "voluntary" means, and the candidate would
#: never see it happen.
#:
#: There is a mechanical reason too: a stored `RaceEthnicity` member would
#: have to be translated into whichever option label this portal happens to
#: use, and a near-miss there submits a demographic answer the candidate
#: never gave.
#:
#: These are still *recognized* rather than left unknown, because "this is
#: the EEO question, it's yours to answer" is far more useful to a reviewer
#: than "unrecognized field", and because it makes the refusal a property of
#: the domain instead of an omission a later contributor could fill in by
#: accident.
REQUIRES_CANDIDATE_ANSWER: frozenset[ApplicationFieldSlot] = frozenset(
    {ApplicationFieldSlot.EEO_SELF_IDENTIFICATION}
)


def requires_candidate_answer(slot: ApplicationFieldSlot) -> bool:
    """Whether `slot` must be answered by the candidate rather than autofilled."""
    return slot in REQUIRES_CANDIDATE_ANSWER


def is_sensitive_slot(slot: ApplicationFieldSlot) -> bool:
    """Whether `slot` carries sensitive data — see `SENSITIVE_SLOTS`."""
    return slot in SENSITIVE_SLOTS


def sensitivity_of(slot: ApplicationFieldSlot) -> FieldSensitivity | None:
    """The slot's sensitivity category, or None if it isn't sensitive."""
    return SENSITIVE_SLOTS.get(slot)


def is_document_slot(slot: ApplicationFieldSlot) -> bool:
    """Whether `slot` is answered from a generated document snapshot."""
    return slot in DOCUMENT_SLOTS
