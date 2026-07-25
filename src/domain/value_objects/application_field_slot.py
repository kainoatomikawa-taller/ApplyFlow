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

Slots ApplyFlow will never answer
---------------------------------
`WORK_AUTHORIZATION` and `EEO_SELF_IDENTIFICATION` are recognized and then
always withheld — see `REQUIRES_CANDIDATE_ANSWER`.
"""

from __future__ import annotations

from enum import StrEnum


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
    FIELD_OF_STUDY = "field_of_study"
    EDUCATION_START_DATE = "education_start_date"
    EDUCATION_END_DATE = "education_end_date"

    # ---- Documents --------------------------------------------------------
    #: Answered from the stored `ApplicationDocument` snapshot for this job,
    #: never from the profile — see `DOCUMENT_SLOTS`.
    RESUME = "resume"
    COVER_LETTER = "cover_letter"

    # ---- Recognized, never answered --------------------------------------
    WORK_AUTHORIZATION = "work_authorization"
    EEO_SELF_IDENTIFICATION = "eeo_self_identification"


#: Slots answered from a generated document rather than from profile data.
#: The medium is the form's business, not the slot's: a resume field may be
#: a file input on one portal and a textarea on the next, and both are
#: `RESUME`.
DOCUMENT_SLOTS: frozenset[ApplicationFieldSlot] = frozenset(
    {ApplicationFieldSlot.RESUME, ApplicationFieldSlot.COVER_LETTER}
)


#: Slots ApplyFlow recognizes and then deliberately refuses to answer.
#:
#: Both are sensitive self-identification (`WorkAuthorization`,
#: `EeoSelfIdentification`), and both are stored only when a candidate
#: explicitly went through the flow that records them — so there is nothing
#: to default and nothing to infer. Even with data on file, autofilling
#: them would mean translating a stored enum member into whichever option
#: label this particular portal happens to use, and a
#: near-miss there submits a demographic or immigration answer the
#: candidate never gave. These are surfaced for the candidate to answer
#: themselves, every time.
#:
#: They are still *recognized* rather than left unknown, because "this is
#: the visa question, answer it yourself" is a far more useful thing to
#: hand a reviewer than "unrecognized field", and because it makes the
#: refusal a property of the domain instead of an omission a later
#: contributor could fill in by accident.
REQUIRES_CANDIDATE_ANSWER: frozenset[ApplicationFieldSlot] = frozenset(
    {
        ApplicationFieldSlot.WORK_AUTHORIZATION,
        ApplicationFieldSlot.EEO_SELF_IDENTIFICATION,
    }
)


def requires_candidate_answer(slot: ApplicationFieldSlot) -> bool:
    """Whether `slot` must be answered by the candidate rather than autofilled."""
    return slot in REQUIRES_CANDIDATE_ANSWER


def is_document_slot(slot: ApplicationFieldSlot) -> bool:
    """Whether `slot` is answered from a generated document snapshot."""
    return slot in DOCUMENT_SLOTS
