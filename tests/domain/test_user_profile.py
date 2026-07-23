from datetime import date

import pytest

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import BusinessRuleViolationError, InvalidValueError
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel


def _profile() -> UserProfile:
    return UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
    )


def test_empty_full_name_rejected():
    with pytest.raises(InvalidValueError):
        UserProfile(
            id="x",
            user_id="user-1",
            full_name="  ",
            email=EmailAddress("jane@example.com"),
        )


def test_empty_user_id_rejected():
    with pytest.raises(InvalidValueError):
        UserProfile(
            id="x",
            user_id="",
            full_name="Jane Doe",
            email=EmailAddress("jane@example.com"),
        )


def test_add_work_history_appends_entry():
    profile = _profile()
    entry = WorkHistoryEntry(
        id="wh-1",
        company_name="Acme",
        job_title="Engineer",
        start_date=date(2020, 1, 1),
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
        )


def test_add_education_appends_entry():
    profile = _profile()
    entry = EducationEntry(
        id="ed-1", institution_name="State University", degree="B.S. Computer Science"
    )
    profile.add_education(entry)
    assert profile.education == [entry]


def test_add_skill_appends_and_rejects_case_insensitive_duplicate():
    profile = _profile()
    profile.add_skill(
        Skill(id="sk-1", name="Python", proficiency=ProficiencyLevel.EXPERT)
    )
    with pytest.raises(BusinessRuleViolationError):
        profile.add_skill(Skill(id="sk-2", name="python"))


def test_skill_negative_years_of_experience_rejected():
    with pytest.raises(InvalidValueError):
        Skill(id="sk-1", name="Python", years_of_experience=-1)
