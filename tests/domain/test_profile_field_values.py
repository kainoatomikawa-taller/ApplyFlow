"""Tests for `resolve_profile_field` — what a profile can state per slot,
and, just as importantly, when it states nothing."""

from datetime import date

import pytest

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.services.profile_field_values import resolve_profile_field
from src.domain.value_objects.address import Address
from src.domain.value_objects.application_field_slot import (
    SENSITIVE_SLOTS,
    ApplicationFieldSlot,
)
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import WorkAuthorizationStatus

Slot = ApplicationFieldSlot


def make_profile(**overrides) -> UserProfile:
    defaults = {
        "id": "profile-1",
        "user_id": "user-1",
        "full_name": "Dana Reyes",
        "email": EmailAddress("dana@example.com"),
        "contact_source": ProvenanceSource.USER_ENTERED,
    }
    return UserProfile(**{**defaults, **overrides})


@pytest.fixture
def full_profile() -> UserProfile:
    """A profile with every mappable standard field populated."""
    profile = make_profile(phone="+1 512 555 0100", location="Austin, TX")
    profile.set_address(
        Address(
            street_address="120 Congress Ave",
            city="Austin",
            state_or_region="TX",
            postal_code="78701",
            country="United States",
        ),
        ProvenanceSource.USER_ENTERED,
    )
    profile.set_links(
        ProfileLinks(
            portfolio_url="https://dana.dev",
            linkedin_url="https://www.linkedin.com/in/danareyes",
            github_url="https://github.com/danareyes",
        ),
        ProvenanceSource.USER_ENTERED,
    )
    profile.add_education(
        EducationEntry(
            id="edu-1",
            institution_name="UT Austin",
            degree="B.S.",
            field_of_study="Computer Science",
            start_date=date(2012, 8, 1),
            end_date=date(2016, 5, 15),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id="job-1",
            company_name="Acme Corp",
            job_title="Staff Engineer",
            start_date=date(2021, 2, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    return profile


# ---- Values read verbatim ----------------------------------------------------


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        (Slot.FULL_NAME, "Dana Reyes"),
        (Slot.EMAIL, "dana@example.com"),
        (Slot.PHONE, "+1 512 555 0100"),
        (Slot.LOCATION, "Austin, TX"),
        (Slot.STREET_ADDRESS, "120 Congress Ave"),
        (Slot.CITY, "Austin"),
        (Slot.STATE_OR_REGION, "TX"),
        (Slot.POSTAL_CODE, "78701"),
        (Slot.COUNTRY, "United States"),
        (Slot.LINKEDIN_URL, "https://www.linkedin.com/in/danareyes"),
        (Slot.GITHUB_URL, "https://github.com/danareyes"),
        (Slot.PORTFOLIO_URL, "https://dana.dev"),
        (Slot.SCHOOL, "UT Austin"),
        (Slot.DEGREE, "B.S."),
        (Slot.FIELD_OF_STUDY, "Computer Science"),
        (Slot.EDUCATION_START_DATE, "2012-08-01"),
        (Slot.EDUCATION_END_DATE, "2016-05-15"),
        (Slot.CURRENT_COMPANY, "Acme Corp"),
        (Slot.CURRENT_TITLE, "Staff Engineer"),
    ],
)
def test_stored_facts_are_returned_verbatim(full_profile, slot, expected):
    resolved = resolve_profile_field(full_profile, slot)
    assert resolved is not None
    assert resolved.text == expected
    assert resolved.is_derived is False


# ---- Derived values ----------------------------------------------------------


@pytest.mark.parametrize(
    ("full_name", "first", "last"),
    [
        ("Dana Reyes", "Dana", "Reyes"),
        ("Ada King Lovelace", "Ada King", "Lovelace"),
        ("  Dana   Reyes  ", "Dana", "Reyes"),
    ],
)
def test_first_and_last_name_are_split_and_flagged_derived(full_name, first, last):
    profile = make_profile(full_name=full_name)

    resolved_first = resolve_profile_field(profile, Slot.FIRST_NAME)
    resolved_last = resolve_profile_field(profile, Slot.LAST_NAME)

    assert resolved_first is not None and resolved_first.text == first
    assert resolved_last is not None and resolved_last.text == last
    # The flag is what sends a reviewer's attention here first: the profile
    # stores one name and the form asked for two.
    assert resolved_first.is_derived is True
    assert resolved_last.is_derived is True


def test_a_single_token_name_is_not_split():
    """There is no family name to take, so both halves are refused rather
    than one of them inventing the other."""
    profile = make_profile(full_name="Prince")
    assert resolve_profile_field(profile, Slot.FIRST_NAME) is None
    assert resolve_profile_field(profile, Slot.LAST_NAME) is None
    # The full name itself is still perfectly answerable.
    full = resolve_profile_field(profile, Slot.FULL_NAME)
    assert full is not None and full.text == "Prince"


def test_location_falls_back_to_composing_the_address():
    profile = make_profile()
    profile.set_address(
        Address(city="Lisbon", country="Portugal"), ProvenanceSource.USER_ENTERED
    )

    resolved = resolve_profile_field(profile, Slot.LOCATION)

    assert resolved is not None
    assert resolved.text == "Lisbon, Portugal"
    assert resolved.is_derived is True


def test_an_explicit_location_is_preferred_over_the_composed_one(full_profile):
    """The candidate wrote "Austin, TX" themselves; that is the fact, and
    composing over it would be substituting our phrasing for theirs."""
    resolved = resolve_profile_field(full_profile, Slot.LOCATION)
    assert resolved is not None
    assert resolved.text == "Austin, TX"
    assert resolved.is_derived is False


# ---- Absence -----------------------------------------------------------------


@pytest.mark.parametrize(
    "slot",
    [
        Slot.PHONE,
        Slot.LOCATION,
        Slot.STREET_ADDRESS,
        Slot.CITY,
        Slot.STATE_OR_REGION,
        Slot.POSTAL_CODE,
        Slot.COUNTRY,
        Slot.LINKEDIN_URL,
        Slot.GITHUB_URL,
        Slot.PORTFOLIO_URL,
        Slot.SCHOOL,
        Slot.DEGREE,
        Slot.FIELD_OF_STUDY,
        Slot.EDUCATION_START_DATE,
        Slot.EDUCATION_END_DATE,
        Slot.CURRENT_COMPANY,
        Slot.CURRENT_TITLE,
    ],
)
def test_a_bare_profile_answers_nothing_optional(slot):
    """A profile holding only the required contact fields must answer None
    everywhere else — never a placeholder, never an empty string."""
    assert resolve_profile_field(make_profile(), slot) is None


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_whitespace_only_stored_value_counts_as_absent(blank):
    profile = make_profile(phone=blank)
    assert resolve_profile_field(profile, Slot.PHONE) is None


def test_address_line_2_is_recognized_and_declined(full_profile):
    """Still exists to be recognized and declined — the profile stores one
    street-address line, so there is nothing to answer a second with.

    `MIDDLE_NAME` and `PREFERRED_NAME` used to be tested here alongside it. The
    profile now stores both, and they have their own tests below.
    """
    assert resolve_profile_field(full_profile, Slot.ADDRESS_LINE_2) is None


# ---- The two "other names", and what their absence means --------------------
#
# These are the only slots whose *empty* answer is a real answer rather than a
# gap, so they get their own section.


def test_a_stated_middle_name_is_answered_verbatim():
    profile = make_profile(middle_name="Andrew")
    resolved = resolve_profile_field(profile, Slot.MIDDLE_NAME)
    assert resolved is not None
    assert resolved.text == "Andrew"
    assert not resolved.is_derived


def test_no_middle_name_answers_empty_rather_than_none():
    """The decision that keeps a person with no middle name from being asked
    about it on every application: blank on the profile means "I have none", so
    the slot is *answered* with nothing rather than left unanswerable.

    `None` here would mean "the profile cannot say", which surfaces the field
    every single time. The planner is what turns this empty answer into a blank
    box — and what still surfaces it if the portal marks the field required.
    """
    resolved = resolve_profile_field(make_profile(), Slot.MIDDLE_NAME)
    assert resolved is not None, "an absent middle name is an answer, not a gap"
    assert resolved.text == ""


def test_a_stated_preferred_name_is_answered_verbatim():
    profile = make_profile(full_name="Michael Andrew Smith", preferred_name="Mike")
    resolved = resolve_profile_field(profile, Slot.PREFERRED_NAME)
    assert resolved is not None
    assert resolved.text == "Mike"
    assert not resolved.is_derived


def test_no_preferred_name_falls_back_to_the_first_name():
    """Blank means "the same name I go by legally" — and for a preferred-name
    field that is the *first* name, not the whole legal name: these boxes expect
    "Michael", not "Michael Andrew Smith".

    Flagged derived, like first and last name, so a review screen can show that
    ApplyFlow chose how to present the candidate's data rather than reading a
    field they filled.
    """
    profile = make_profile(full_name="Michael Andrew Smith")
    resolved = resolve_profile_field(profile, Slot.PREFERRED_NAME)
    assert resolved is not None
    assert resolved.text == "Michael Andrew"
    assert resolved.is_derived


def test_a_single_token_name_cannot_answer_the_preferred_name_slot():
    """The fallback goes through the same name split as first/last name, which
    declines a one-token name — there is no family name to separate off, so
    nothing is inferred."""
    profile = make_profile(full_name="Prince")
    assert resolve_profile_field(profile, Slot.PREFERRED_NAME) is None


@pytest.mark.parametrize("slot", [Slot.RESUME, Slot.COVER_LETTER])
def test_document_slots_are_not_answered_from_the_profile(full_profile, slot):
    """They are answered from a stored `ApplicationDocument`, which is not
    this function's business."""
    assert resolve_profile_field(full_profile, slot) is None


# ---- Refusal ----------------------------------------------------------------


@pytest.mark.parametrize("slot", sorted(SENSITIVE_SLOTS))
def test_every_sensitive_slot_is_refused_by_the_generic_resolver(full_profile, slot):
    """A refusal, not an absence: the data is right there on the profile and
    this function still will not hand it out.

    Sensitive fields are governed by `decide_sensitive_field`, which applies
    rules this resolver has no business duplicating — attestation, exact
    answers, and the unconditional refusal of EEO. The guard is here so the
    two paths cannot be crossed by accident: a contributor who routes a visa
    question through the ordinary resolver gets nothing back rather than a
    quietly-filled legal declaration."""
    full_profile.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            citizenship_country="United States",
            requires_sponsorship=False,
            source=ProvenanceSource.ANSWER,
        )
    )
    full_profile.set_eeo_self_identification(
        EeoSelfIdentification(source=ProvenanceSource.ANSWER)
    )

    assert resolve_profile_field(full_profile, slot) is None


# ---- Selection among several stored entries ---------------------------------


def test_the_most_recent_education_answers_the_single_education_block():
    profile = make_profile()
    for entry_id, institution, end in [
        ("edu-1", "State College", date(2014, 5, 1)),
        ("edu-2", "Grad School", date(2019, 6, 1)),
        ("edu-3", "Community College", date(2011, 5, 1)),
    ]:
        profile.add_education(
            EducationEntry(
                id=entry_id,
                institution_name=institution,
                degree="Degree",
                start_date=date(end.year - 2, 9, 1),
                end_date=end,
                source=ProvenanceSource.PARSED_RESUME,
            )
        )

    school = resolve_profile_field(profile, Slot.SCHOOL)
    assert school is not None and school.text == "Grad School"


def test_an_in_progress_program_is_ranked_by_its_start_date():
    """No end date yet, so the start date is what places it — otherwise the
    current program would sort behind every finished one."""
    profile = make_profile()
    profile.add_education(
        EducationEntry(
            id="edu-1",
            institution_name="State College",
            degree="B.A.",
            start_date=date(2014, 9, 1),
            end_date=date(2018, 5, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    profile.add_education(
        EducationEntry(
            id="edu-2",
            institution_name="Night School",
            degree="M.S.",
            start_date=date(2024, 9, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )

    school = resolve_profile_field(profile, Slot.SCHOOL)
    assert school is not None and school.text == "Night School"
    # ...and the end date it does not have is not invented.
    assert resolve_profile_field(profile, Slot.EDUCATION_END_DATE) is None


def test_an_ongoing_role_answers_current_company_over_a_later_started_past_one():
    profile = make_profile()
    profile.add_work_history(
        WorkHistoryEntry(
            id="job-1",
            company_name="Still Here Inc",
            job_title="Principal Engineer",
            start_date=date(2020, 1, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id="job-2",
            company_name="Short Stint LLC",
            job_title="Contractor",
            start_date=date(2023, 1, 1),
            end_date=date(2023, 6, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )

    company = resolve_profile_field(profile, Slot.CURRENT_COMPANY)
    assert company is not None and company.text == "Still Here Inc"


def test_a_between_jobs_candidate_answers_with_their_most_recent_role():
    """The form is asking where they last worked, and the record answers
    that — blanking the field would be less true, not more."""
    profile = make_profile()
    profile.add_work_history(
        WorkHistoryEntry(
            id="job-1",
            company_name="Older Corp",
            job_title="Engineer",
            start_date=date(2015, 1, 1),
            end_date=date(2018, 1, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id="job-2",
            company_name="Recent Corp",
            job_title="Senior Engineer",
            start_date=date(2019, 1, 1),
            end_date=date(2024, 1, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )

    company = resolve_profile_field(profile, Slot.CURRENT_COMPANY)
    title = resolve_profile_field(profile, Slot.CURRENT_TITLE)
    assert company is not None and company.text == "Recent Corp"
    assert title is not None and title.text == "Senior Engineer"


# ---- Coverage of the enum ---------------------------------------------------


#: The one slot whose answer may legitimately be an empty string: a blank
#: `middle_name` is the candidate stating they have none. Every other slot must
#: either answer with real text or answer None — an empty string anywhere else
#: would be a placeholder reaching a form, which is what this test exists to
#: prevent.
_MAY_ANSWER_EMPTY = frozenset({ApplicationFieldSlot.MIDDLE_NAME})


def test_every_slot_is_accounted_for(full_profile):
    """No slot may raise, and none may return a value on a profile that
    doesn't back it — the enum and the resolver table cannot drift apart
    without this failing."""
    for slot in ApplicationFieldSlot:
        resolved = resolve_profile_field(full_profile, slot)
        if resolved is None:
            continue
        if slot in _MAY_ANSWER_EMPTY:
            continue
        assert resolved.text.strip(), f"{slot} answered with blank text"


def test_only_the_middle_name_slot_may_answer_with_nothing():
    """Pins the exemption above so it cannot quietly widen. An empty answer means
    "I have none of this", and that reading is only true for a middle name — for
    a phone number or a postal code it would put a blank into a form and report
    it as filled."""
    profile = make_profile()
    for slot in ApplicationFieldSlot:
        if slot in _MAY_ANSWER_EMPTY:
            continue
        resolved = resolve_profile_field(profile, slot)
        assert resolved is None or resolved.text.strip(), (
            f"{slot} answered with an empty string; only "
            f"{sorted(_MAY_ANSWER_EMPTY)} may do that"
        )
