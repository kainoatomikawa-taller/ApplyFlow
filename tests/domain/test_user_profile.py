from datetime import date

import pytest

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import BusinessRuleViolationError, InvalidValueError
from src.domain.value_objects.address import Address
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)


def _profile() -> UserProfile:
    return UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )


def test_empty_full_name_rejected():
    with pytest.raises(InvalidValueError):
        UserProfile(
            id="x",
            user_id="user-1",
            full_name="  ",
            email=EmailAddress("jane@example.com"),
            contact_source=ProvenanceSource.USER_ENTERED,
        )


def test_empty_user_id_rejected():
    with pytest.raises(InvalidValueError):
        UserProfile(
            id="x",
            user_id="",
            full_name="Jane Doe",
            email=EmailAddress("jane@example.com"),
            contact_source=ProvenanceSource.USER_ENTERED,
        )


def test_add_work_history_appends_entry():
    profile = _profile()
    entry = WorkHistoryEntry(
        id="wh-1",
        company_name="Acme",
        job_title="Engineer",
        start_date=date(2020, 1, 1),
        source=ProvenanceSource.PARSED_RESUME,
    )
    profile.add_work_history(entry)
    assert profile.work_history == [entry]
    assert entry.is_current


def test_duplicate_work_history_id_rejected():
    profile = _profile()
    entry = WorkHistoryEntry(
        id="wh-1",
        company_name="Acme",
        job_title="Engineer",
        start_date=date(2020, 1, 1),
        source=ProvenanceSource.PARSED_RESUME,
    )
    profile.add_work_history(entry)
    with pytest.raises(BusinessRuleViolationError):
        profile.add_work_history(entry)


def test_work_history_end_date_before_start_date_rejected():
    with pytest.raises(InvalidValueError):
        WorkHistoryEntry(
            id="wh-1",
            company_name="Acme",
            job_title="Engineer",
            start_date=date(2020, 1, 1),
            end_date=date(2019, 1, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )


def test_add_education_appends_entry():
    profile = _profile()
    entry = EducationEntry(
        id="ed-1",
        institution_name="State University",
        degree="B.S. Computer Science",
        source=ProvenanceSource.PARSED_RESUME,
    )
    profile.add_education(entry)
    assert profile.education == [entry]


def test_add_skill_appends_and_rejects_case_insensitive_duplicate():
    profile = _profile()
    profile.add_skill(
        Skill(
            id="sk-1",
            name="Python",
            proficiency=ProficiencyLevel.EXPERT,
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    with pytest.raises(BusinessRuleViolationError):
        profile.add_skill(
            Skill(id="sk-2", name="python", source=ProvenanceSource.USER_ENTERED)
        )


def test_skill_negative_years_of_experience_rejected():
    with pytest.raises(InvalidValueError):
        Skill(
            id="sk-1",
            name="Python",
            years_of_experience=-1,
            source=ProvenanceSource.PARSED_RESUME,
        )


def test_new_profile_never_defaults_sensitive_fields():
    profile = _profile()
    assert profile.work_authorization is None
    assert profile.eeo_self_identification is None
    assert profile.address == Address()
    assert profile.links == ProfileLinks()
    assert profile.address_source is None
    assert profile.links_source is None


def test_set_address_and_links():
    profile = _profile()
    address = Address(city="San Francisco", state_or_region="CA", country="USA")
    links = ProfileLinks(linkedin_url="https://linkedin.com/in/janedoe")

    profile.set_address(address, source=ProvenanceSource.USER_ENTERED)
    profile.set_links(links, source=ProvenanceSource.PARSED_RESUME)

    assert profile.address == address
    assert profile.address_source is ProvenanceSource.USER_ENTERED
    assert profile.links == links
    assert profile.links_source is ProvenanceSource.PARSED_RESUME


def test_set_work_authorization_and_clear_it():
    profile = _profile()
    work_authorization = WorkAuthorization(
        status=WorkAuthorizationStatus.CITIZEN, source=ProvenanceSource.ANSWER
    )

    profile.set_work_authorization(work_authorization)
    assert profile.work_authorization == work_authorization

    profile.set_work_authorization(None)
    assert profile.work_authorization is None


def test_set_eeo_self_identification_and_clear_it():
    profile = _profile()
    eeo = EeoSelfIdentification(source=ProvenanceSource.ANSWER)

    profile.set_eeo_self_identification(eeo)
    assert profile.eeo_self_identification == eeo

    profile.set_eeo_self_identification(None)
    assert profile.eeo_self_identification is None


# ---- Provenance -------------------------------------------------------------


def test_profile_requires_a_valid_contact_source():
    with pytest.raises(InvalidValueError):
        UserProfile(
            id="x",
            user_id="user-1",
            full_name="Jane Doe",
            email=EmailAddress("jane@example.com"),
            contact_source="user_entered",  # a raw string, not the enum
        )


def test_setting_address_without_a_source_is_rejected():
    profile = _profile()
    address = Address(city="San Francisco")
    with pytest.raises(InvalidValueError):
        profile.set_address(address)  # source=None but address has data


def test_clearing_address_needs_no_source():
    """An empty address/links group isn't a fact yet, so no source is
    needed to clear it back to empty."""
    profile = _profile()
    profile.set_address(Address(city="San Francisco"), source=ProvenanceSource.ANSWER)
    profile.set_address(Address())  # clearing — no source required
    assert profile.address == Address()
    assert profile.address_source is None


def test_setting_links_without_a_source_is_rejected():
    profile = _profile()
    links = ProfileLinks(github_url="https://github.com/janedoe")
    with pytest.raises(InvalidValueError):
        profile.set_links(links)


@pytest.mark.parametrize(
    "build_fact",
    [
        lambda: WorkHistoryEntry(
            id="wh-1",
            company_name="Acme",
            job_title="Engineer",
            start_date=date(2020, 1, 1),
            source="user_entered",  # a raw string, not the enum
        ),
        lambda: EducationEntry(
            id="ed-1",
            institution_name="State University",
            degree="B.S.",
            source="user_entered",
        ),
        lambda: Skill(id="sk-1", name="Python", source="user_entered"),
        lambda: WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN, source="answer"
        ),
        lambda: EeoSelfIdentification(source="answer"),
    ],
)
def test_facts_reject_a_raw_string_in_place_of_a_provenance_source(build_fact):
    with pytest.raises(InvalidValueError):
        build_fact()
