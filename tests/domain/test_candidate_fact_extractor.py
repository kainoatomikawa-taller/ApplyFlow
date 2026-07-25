"""Tests for CandidateFactExtractor — turns a UserProfile into plain-
language fact strings, never inventing a fact the profile doesn't state.
"""

from __future__ import annotations

from datetime import date

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.services.candidate_fact_extractor import CandidateFactExtractor
from src.domain.value_objects.address import Address
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.profile_links import ProfileLinks
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


# ---- extract_provenance_backed ----------------------------------------------
#
# The generation-side view: every fact tagged with the source the data model
# records for it, and nothing that has no source to cite.


def _provenance_backed(profile: UserProfile):
    return CandidateFactExtractor().extract_provenance_backed(profile)


def test_contact_facts_carry_the_profiles_contact_source():
    profile = _profile(
        contact_source=ProvenanceSource.PARSED_RESUME,
        phone="+1-555-0100",
        headline="Backend engineer",
        location="Austin, TX",
    )

    facts = _provenance_backed(profile)

    assert all(fact.source is ProvenanceSource.PARSED_RESUME for fact in facts)
    texts = [fact.text for fact in facts]
    assert "Name: Jane Doe" in texts
    assert "Email: jane@example.com" in texts
    assert any("+1-555-0100" in text for text in texts)
    assert any("Backend engineer" in text for text in texts)
    assert any("Austin, TX" in text for text in texts)


def test_each_child_entry_is_attributed_to_its_own_source():
    profile = _profile(
        contact_source=ProvenanceSource.USER_ENTERED,
        work_history=[
            WorkHistoryEntry(
                id="job-1",
                company_name="Acme Corp",
                job_title="Software Engineer",
                start_date=date(2021, 1, 1),
                end_date=date(2023, 1, 1),
                location="Remote",
                description="Built payment services.",
                source=ProvenanceSource.PARSED_RESUME,
            )
        ],
        skills=[Skill(id="s1", name="Python", source=ProvenanceSource.ANSWER)],
    )

    by_source = {fact.text: fact.source for fact in _provenance_backed(profile)}

    assert by_source[
        "Worked as Software Engineer at Acme Corp (2021-01-01 to 2023-01-01)"
    ] is (ProvenanceSource.PARSED_RESUME)
    assert by_source["Skill: Python"] is ProvenanceSource.ANSWER
    assert any(
        "Built payment services." in text and source is ProvenanceSource.PARSED_RESUME
        for text, source in by_source.items()
    )
    assert any("Remote" in text for text in by_source)


def test_education_is_included_so_a_resume_can_state_it():
    profile = _profile(
        education=[
            EducationEntry(
                id="edu-1",
                institution_name="State University",
                degree="Bachelor of Science",
                field_of_study="Computer Science",
                end_date=date(2020, 5, 1),
                description="Graduated with honors.",
                source=ProvenanceSource.PARSED_RESUME,
            )
        ]
    )

    texts = [fact.text for fact in _provenance_backed(profile)]

    assert any(
        "Bachelor of Science" in text
        and "Computer Science" in text
        and "State University" in text
        for text in texts
    )
    assert any("Graduated with honors." in text for text in texts)


def test_work_authorization_keeps_its_own_source():
    profile = _profile(
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            source=ProvenanceSource.ANSWER,
        )
    )

    matches = [
        fact
        for fact in _provenance_backed(profile)
        if "Work authorization" in fact.text
    ]

    assert [fact.source for fact in matches] == [ProvenanceSource.ANSWER]


def test_address_and_links_are_attributed_to_their_group_sources():
    profile = _profile(
        address=Address(city="Austin", country="United States"),
        address_source=ProvenanceSource.USER_ENTERED,
        links=ProfileLinks(github_url="https://github.com/jane"),
        links_source=ProvenanceSource.PARSED_RESUME,
    )

    by_text = {fact.text: fact.source for fact in _provenance_backed(profile)}

    assert by_text["Address: Austin, United States"] is ProvenanceSource.USER_ENTERED
    assert by_text["GitHub: https://github.com/jane"] is ProvenanceSource.PARSED_RESUME


def test_untagged_scalar_fields_are_excluded_because_nothing_can_vouch_for_them():
    """`highest_degree`/`clearance_level` carry no `*_source` in the data
    model, so they cannot back a generated claim — a degree assertion has
    to come from a real EducationEntry instead."""
    profile = _profile(
        highest_degree=DegreeLevel.MASTERS,
        clearance_level=ClearanceLevel.SECRET,
    )

    texts = [fact.text for fact in _provenance_backed(profile)]

    assert not any("Master" in text for text in texts)
    assert not any("clearance" in text.lower() for text in texts)


def test_the_derived_experience_total_is_excluded_from_provenance_backed_facts():
    """ "N years of professional work experience" is computed here, not
    stated by any resume, form, or answer — tagging it with a source would
    be exactly the kind of small fabrication this module prevents. The
    underlying dated roles are included, and they are what a claim about
    tenure must rest on."""
    profile = _profile(
        work_history=[
            WorkHistoryEntry(
                id="job-1",
                company_name="Acme Corp",
                job_title="Software Engineer",
                start_date=date(2021, 1, 1),
                end_date=date(2023, 1, 1),
                source=ProvenanceSource.PARSED_RESUME,
            )
        ]
    )

    texts = [fact.text for fact in _provenance_backed(profile)]

    assert not any("years of professional work experience" in text for text in texts)
    assert any("2021-01-01" in text for text in texts)


def test_a_bare_profile_still_yields_its_contact_facts_and_nothing_else():
    facts = _provenance_backed(_profile())

    assert [fact.text for fact in facts] == [
        "Name: Jane Doe",
        "Email: jane@example.com",
    ]
