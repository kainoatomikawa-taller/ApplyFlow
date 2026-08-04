"""Tests for the profile's editing API — the mutators an editable profile needs.

`test_user_profile.py` covers the aggregate's invariants and the three `add_*`
methods. This file covers what was missing until the profile became editable:
replacing the contact group, and updating or removing an entry in one of the
three lists.

Two properties recur and are the reason these methods exist at all rather than
callers assigning attributes:

* **`updated_at` moves.** Direct attribute assignment skips `_touch()`, so a
  profile edited that way would keep reporting the timestamp of its last
  *structural* change. Nothing could write the contact fields before, so this
  was latent rather than broken; an editor makes it reachable.
* **An edit against an unknown id is refused, never turned into an insert.** A
  stale id means the caller is working from a list that has since changed, and
  silently appending a duplicate is the one outcome nobody expects from a
  control labelled "edit".
"""

from __future__ import annotations

from datetime import date

import pytest

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    ProfileEntryNotFoundError,
)
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.domain.value_objects.provenance_source import ProvenanceSource

_USER_ENTERED = ProvenanceSource.USER_ENTERED
_PARSED = ProvenanceSource.PARSED_RESUME


def _profile() -> UserProfile:
    return UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        contact_source=_PARSED,
    )


def _job(entry_id: str = "job-1", *, title: str = "Engineer") -> WorkHistoryEntry:
    return WorkHistoryEntry(
        id=entry_id,
        company_name="Initech",
        job_title=title,
        start_date=date(2020, 1, 1),
        source=_PARSED,
    )


def _school(entry_id: str = "edu-1", *, degree: str = "BSc") -> EducationEntry:
    return EducationEntry(
        id=entry_id,
        institution_name="State University",
        degree=degree,
        source=_PARSED,
    )


def _skill(entry_id: str = "skill-1", *, name: str = "Python") -> Skill:
    return Skill(id=entry_id, name=name, source=_PARSED)


# -- Contact details ----------------------------------------------------------


def test_setting_contact_details_replaces_the_whole_group() -> None:
    profile = _profile()
    profile.set_contact_details(
        full_name="Jane Q. Okonkwo",
        email=EmailAddress("jane.okonkwo@example.com"),
        source=_USER_ENTERED,
        phone="+1 555 010 9999",
        headline="Backend engineer",
        location="Austin, TX",
        middle_name="Quinn",
        preferred_name="JQ",
    )

    assert profile.full_name == "Jane Q. Okonkwo"
    assert str(profile.email) == "jane.okonkwo@example.com"
    assert profile.phone == "+1 555 010 9999"
    assert profile.headline == "Backend engineer"
    assert profile.location == "Austin, TX"
    assert profile.middle_name == "Quinn"
    assert profile.preferred_name == "JQ"


def test_setting_contact_details_restamps_the_provenance() -> None:
    """The point of the editor for a résumé-built profile: what the candidate
    typed is theirs, not the parser's. `WorkAuthorization` is the field where
    that distinction gates autofill, but the tag has to be honest everywhere."""
    profile = _profile()
    assert profile.contact_source is _PARSED

    profile.set_contact_details(
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        source=_USER_ENTERED,
    )

    assert profile.contact_source is _USER_ENTERED


def test_omitting_an_optional_contact_field_clears_it() -> None:
    """A full replacement, not a patch. Leaving a field out of the call is how
    the candidate deletes it — otherwise a cleared phone number would be
    indistinguishable from one the caller did not mention."""
    profile = _profile()
    profile.set_contact_details(
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        source=_USER_ENTERED,
        phone="+1 555 010 9999",
        middle_name="Quinn",
    )

    profile.set_contact_details(
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        source=_USER_ENTERED,
    )

    assert profile.phone is None
    assert profile.middle_name is None
    assert profile.preferred_name is None


def test_setting_contact_details_moves_updated_at() -> None:
    profile = _profile()
    before = profile.updated_at
    profile.set_contact_details(
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        source=_USER_ENTERED,
    )
    assert profile.updated_at > before


def test_contact_details_still_refuse_an_empty_name() -> None:
    """The constructor's invariant, enforced on the edit path too — otherwise
    the one way to violate it would be to save the form with the name blanked."""
    profile = _profile()
    with pytest.raises(InvalidValueError):
        profile.set_contact_details(
            full_name="   ",
            email=EmailAddress("jane@example.com"),
            source=_USER_ENTERED,
        )


def test_contact_details_require_a_real_provenance_source() -> None:
    profile = _profile()
    with pytest.raises(InvalidValueError):
        profile.set_contact_details(
            full_name="Jane Doe",
            email=EmailAddress("jane@example.com"),
            source="user_entered",  # type: ignore[arg-type]
        )


# -- Work history -------------------------------------------------------------


def test_updating_a_work_history_entry_replaces_it_in_place() -> None:
    profile = _profile()
    profile.add_work_history(_job("job-1", title="Enginer"))
    profile.add_work_history(_job("job-2", title="Senior Engineer"))

    profile.update_work_history(_job("job-1", title="Engineer"))

    assert [entry.id for entry in profile.work_history] == ["job-1", "job-2"]
    assert profile.work_history[0].job_title == "Engineer"


def test_updating_an_unknown_work_history_entry_is_refused() -> None:
    profile = _profile()
    profile.add_work_history(_job("job-1"))

    with pytest.raises(ProfileEntryNotFoundError) as excinfo:
        profile.update_work_history(_job("job-404"))

    assert excinfo.value.entry_id == "job-404"
    assert len(profile.work_history) == 1, "a stale edit must not append"


def test_removing_a_work_history_entry() -> None:
    profile = _profile()
    profile.add_work_history(_job("job-1"))
    profile.add_work_history(_job("job-2"))

    profile.remove_work_history("job-1")

    assert [entry.id for entry in profile.work_history] == ["job-2"]


def test_removing_an_unknown_work_history_entry_is_refused() -> None:
    profile = _profile()
    with pytest.raises(ProfileEntryNotFoundError):
        profile.remove_work_history("job-404")


def test_work_history_edits_move_updated_at() -> None:
    profile = _profile()
    profile.add_work_history(_job("job-1"))
    before = profile.updated_at
    profile.update_work_history(_job("job-1", title="Staff Engineer"))
    assert profile.updated_at > before


# -- Education ----------------------------------------------------------------


def test_updating_an_education_entry_replaces_it_in_place() -> None:
    profile = _profile()
    profile.add_education(_school("edu-1", degree="BS"))
    profile.add_education(_school("edu-2", degree="MSc"))

    profile.update_education(_school("edu-1", degree="BSc"))

    assert [entry.id for entry in profile.education] == ["edu-1", "edu-2"]
    assert profile.education[0].degree == "BSc"


def test_removing_an_education_entry() -> None:
    profile = _profile()
    profile.add_education(_school("edu-1"))
    profile.remove_education("edu-1")
    assert profile.education == []


def test_unknown_education_ids_are_refused() -> None:
    profile = _profile()
    with pytest.raises(ProfileEntryNotFoundError):
        profile.update_education(_school("edu-404"))
    with pytest.raises(ProfileEntryNotFoundError):
        profile.remove_education("edu-404")


# -- Skills -------------------------------------------------------------------


def test_updating_a_skill_replaces_it_in_place() -> None:
    profile = _profile()
    profile.add_skill(_skill("skill-1", name="Pyton"))

    profile.update_skill(
        Skill(
            id="skill-1",
            name="Python",
            source=_USER_ENTERED,
            proficiency=ProficiencyLevel.ADVANCED,
        )
    )

    assert [skill.name for skill in profile.skills] == ["Python"]
    assert profile.skills[0].proficiency is ProficiencyLevel.ADVANCED


def test_renaming_a_skill_onto_another_skills_name_is_refused() -> None:
    """`add_skill` enforces case-insensitive uniqueness; an edit that walked
    around it would leave the profile holding the duplicate that rule exists to
    prevent."""
    profile = _profile()
    profile.add_skill(_skill("skill-1", name="Python"))
    profile.add_skill(_skill("skill-2", name="Java"))

    with pytest.raises(BusinessRuleViolationError):
        profile.update_skill(_skill("skill-2", name="python"))

    assert [skill.name for skill in profile.skills] == ["Python", "Java"]


def test_recasing_a_skills_own_name_is_allowed() -> None:
    """The uniqueness check compares against every *other* skill, so a skill is
    not blocked by itself — otherwise fixing "pyton" to "Python" would be
    refused as a duplicate of the entry being edited."""
    profile = _profile()
    profile.add_skill(_skill("skill-1", name="python"))

    profile.update_skill(_skill("skill-1", name="Python"))

    assert [skill.name for skill in profile.skills] == ["Python"]


def test_removing_a_skill() -> None:
    profile = _profile()
    profile.add_skill(_skill("skill-1", name="Python"))
    profile.remove_skill("skill-1")
    assert profile.skills == []


def test_unknown_skill_ids_are_refused() -> None:
    profile = _profile()
    with pytest.raises(ProfileEntryNotFoundError):
        profile.update_skill(_skill("skill-404"))
    with pytest.raises(ProfileEntryNotFoundError):
        profile.remove_skill("skill-404")


def test_the_not_found_error_names_the_kind_of_entry() -> None:
    """Three lists share one exception, so the message has to say which one —
    "entry 'x' is not on this profile" is not actionable on its own."""
    profile = _profile()
    with pytest.raises(ProfileEntryNotFoundError) as excinfo:
        profile.remove_education("edu-404")
    assert excinfo.value.entry_kind == "Education"
    assert "Education" in str(excinfo.value)
