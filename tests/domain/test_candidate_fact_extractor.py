"""Tests for CandidateFactExtractor — turns a UserProfile into plain-
language fact strings, never inventing a fact the profile doesn't state.
"""

from __future__ import annotations

from datetime import date

from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.services.candidate_fact_extractor import CandidateFactExtractor
from src.domain.value_objects.address import Address
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)

_AS_OF = date(2026, 1, 1)


def _profile(**overrides: object) -> UserProfile:
    defaults: dict[str, object] = {
        "id": "profile-1",
        "user_id": "user-1",
        "full_name": "Jane Doe",
        "email": EmailAddress("jane@example.com"),
        "contact_source": ProvenanceSource.USER_ENTERED,
    }
    defaults.update(overrides)
    return UserProfile(**defaults)


def test_bare_profile_yields_no_facts():
    facts = CandidateFactExtractor().extract(_profile(), as_of=_AS_OF)
    assert facts == ()


def test_stated_degree_clearance_and_work_authorization_become_facts():
    profile = _profile(
        highest_degree=DegreeLevel.MASTERS,
        clearance_level=ClearanceLevel.SECRET,
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            source=ProvenanceSource.USER_ENTERED,
        ),
    )
    facts = CandidateFactExtractor().extract(profile, as_of=_AS_OF)

    assert any("Master's degree" in fact for fact in facts)
    assert any("Secret clearance" in fact for fact in facts)
    assert any("citizen" in fact.lower() for fact in facts)


def test_work_history_produces_an_experience_total_and_per_role_facts():
    profile = _profile(
        work_history=[
            WorkHistoryEntry(
                id="job-1",
                company_name="Acme Corp",
                job_title="Software Engineer",
                start_date=date(2021, 1, 1),
                end_date=date(2023, 1, 1),
                source=ProvenanceSource.USER_ENTERED,
            )
        ]
    )
    facts = CandidateFactExtractor().extract(profile, as_of=_AS_OF)

    assert any("2 years" in fact for fact in facts)
    assert any("Software Engineer" in fact and "Acme Corp" in fact for fact in facts)


def test_skills_and_location_become_facts():
    profile = _profile(
        skills=[
            Skill(
                id="s1",
                name="Python",
                source=ProvenanceSource.USER_ENTERED,
                years_of_experience=3,
            )
        ],
        address=Address(country="United States"),
        address_source=ProvenanceSource.USER_ENTERED,
    )
    facts = CandidateFactExtractor().extract(profile, as_of=_AS_OF)

    assert any("Python" in fact and "3 years" in fact for fact in facts)
    assert any("United States" in fact for fact in facts)
