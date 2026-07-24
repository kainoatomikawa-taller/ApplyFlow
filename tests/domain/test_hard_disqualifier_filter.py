"""Tests for HardDisqualifierFilter — the mechanism that decides whether a
candidate's profile genuinely fails a job's hard disqualifiers, never its
soft preferences, and never over-filters on data the profile doesn't
state.
"""

from __future__ import annotations

from src.domain.entities.user_profile import UserProfile
from src.domain.services.hard_disqualifier_filter import HardDisqualifierFilter
from src.domain.value_objects.address import Address
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.requirement_category import RequirementCategory
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)


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


def _evaluate(profile: UserProfile, requirements: JobRequirements):
    return HardDisqualifierFilter().evaluate(profile, requirements)


# ---- no hard requirements -----------------------------------------------------------


def test_empty_requirements_always_qualify():
    result = _evaluate(_profile(), JobRequirements())
    assert result.qualifies is True
    assert result.failed == ()


def test_soft_only_requirements_never_disqualify():
    """Wish-list style requirements (unclear degree_required, sponsorship
    available, hybrid location) are never hard, regardless of how sparse
    the candidate's profile is."""
    requirements = JobRequirements(
        degree_level=DegreeLevel.MASTERS,
        degree_required=False,
        clearance_level=ClearanceLevel.SECRET,
        clearance_required=False,
        remote_type=RemoteType.HYBRID,
        locations=("Austin, TX",),
        work_authorization=WorkAuthorizationStatus.REQUIRES_SPONSORSHIP,
        min_years_experience=8,
        required_skills=("Rust",),
    )
    result = _evaluate(_profile(), requirements)
    assert result.qualifies is True
    assert result.failed == ()


# ---- degree -----------------------------------------------------------------------


def test_degree_meeting_the_bar_qualifies():
    requirements = JobRequirements(
        degree_level=DegreeLevel.BACHELORS, degree_required=True
    )
    profile = _profile(highest_degree=DegreeLevel.MASTERS)
    assert _evaluate(profile, requirements).qualifies is True


def test_degree_below_the_bar_is_disqualified():
    requirements = JobRequirements(
        degree_level=DegreeLevel.MASTERS, degree_required=True
    )
    profile = _profile(highest_degree=DegreeLevel.BACHELORS)
    result = _evaluate(profile, requirements)
    assert result.qualifies is False
    assert result.failed[0].category == RequirementCategory.DEGREE


def test_unknown_candidate_degree_is_not_filtered():
    """Acceptance criterion 4 (near-miss protection): a profile that
    hasn't stated a degree at all must not be excluded from a job that
    requires one — missing data is unknown, not a failure."""
    requirements = JobRequirements(
        degree_level=DegreeLevel.BACHELORS, degree_required=True
    )
    result = _evaluate(_profile(), requirements)
    assert result.qualifies is True


# ---- clearance --------------------------------------------------------------------


def test_clearance_meeting_the_bar_qualifies():
    requirements = JobRequirements(
        clearance_level=ClearanceLevel.SECRET, clearance_required=True
    )
    profile = _profile(clearance_level=ClearanceLevel.TOP_SECRET)
    assert _evaluate(profile, requirements).qualifies is True


def test_clearance_below_the_bar_is_disqualified():
    requirements = JobRequirements(
        clearance_level=ClearanceLevel.TOP_SECRET, clearance_required=True
    )
    profile = _profile(clearance_level=ClearanceLevel.SECRET)
    result = _evaluate(profile, requirements)
    assert result.qualifies is False
    assert result.failed[0].category == RequirementCategory.CLEARANCE


def test_unknown_candidate_clearance_is_not_filtered():
    requirements = JobRequirements(
        clearance_level=ClearanceLevel.SECRET, clearance_required=True
    )
    result = _evaluate(_profile(), requirements)
    assert result.qualifies is True


# ---- work authorization --------------------------------------------------------------


def _with_work_auth(status: WorkAuthorizationStatus) -> UserProfile:
    return _profile(
        work_authorization=WorkAuthorization(
            status=status, source=ProvenanceSource.USER_ENTERED
        )
    )


def test_citizen_requirement_satisfied_by_citizen():
    requirements = JobRequirements(work_authorization=WorkAuthorizationStatus.CITIZEN)
    profile = _with_work_auth(WorkAuthorizationStatus.CITIZEN)
    assert _evaluate(profile, requirements).qualifies is True


def test_citizen_requirement_not_satisfied_by_permanent_resident():
    requirements = JobRequirements(work_authorization=WorkAuthorizationStatus.CITIZEN)
    profile = _with_work_auth(WorkAuthorizationStatus.PERMANENT_RESIDENT)
    result = _evaluate(profile, requirements)
    assert result.qualifies is False
    assert result.failed[0].category == RequirementCategory.WORK_AUTHORIZATION


def test_permanent_resident_requirement_satisfied_by_citizen_or_pr():
    requirements = JobRequirements(
        work_authorization=WorkAuthorizationStatus.PERMANENT_RESIDENT
    )
    assert _evaluate(
        _with_work_auth(WorkAuthorizationStatus.CITIZEN), requirements
    ).qualifies is True
    assert _evaluate(
        _with_work_auth(WorkAuthorizationStatus.PERMANENT_RESIDENT), requirements
    ).qualifies is True


def test_permanent_resident_requirement_not_satisfied_by_visa_holder():
    requirements = JobRequirements(
        work_authorization=WorkAuthorizationStatus.PERMANENT_RESIDENT
    )
    profile = _with_work_auth(WorkAuthorizationStatus.VISA_HOLDER)
    assert _evaluate(profile, requirements).qualifies is False


def test_sponsorship_requirement_is_soft_and_never_disqualifies():
    requirements = JobRequirements(
        work_authorization=WorkAuthorizationStatus.REQUIRES_SPONSORSHIP
    )
    profile = _with_work_auth(WorkAuthorizationStatus.NOT_AUTHORIZED)
    assert _evaluate(profile, requirements).qualifies is True


def test_unknown_candidate_work_authorization_is_not_filtered():
    requirements = JobRequirements(work_authorization=WorkAuthorizationStatus.CITIZEN)
    result = _evaluate(_profile(), requirements)
    assert result.qualifies is True


# ---- location / remote --------------------------------------------------------------


def _with_country(country: str) -> UserProfile:
    return _profile(
        address=Address(country=country),
        address_source=ProvenanceSource.USER_ENTERED,
    )


def test_on_site_in_candidates_country_qualifies():
    requirements = JobRequirements(
        remote_type=RemoteType.ON_SITE, locations=("United States",)
    )
    assert _evaluate(_with_country("United States"), requirements).qualifies is True


def test_on_site_country_alias_is_recognized():
    requirements = JobRequirements(
        remote_type=RemoteType.ON_SITE, locations=("United States",)
    )
    assert _evaluate(_with_country("USA"), requirements).qualifies is True


def test_on_site_in_a_different_country_is_disqualified():
    requirements = JobRequirements(
        remote_type=RemoteType.ON_SITE, locations=("Germany",)
    )
    result = _evaluate(_with_country("United States"), requirements)
    assert result.qualifies is False
    assert result.failed[0].category == RequirementCategory.LOCATION


def test_on_site_city_level_location_is_not_filtered():
    """Acceptance criterion 4 (near-miss protection): a job stated as
    on-site in a specific city ("Austin, TX") carries no confident country
    signal, so a candidate elsewhere in the same country — or one whose
    profile just doesn't say — must not be excluded over it."""
    requirements = JobRequirements(
        remote_type=RemoteType.ON_SITE, locations=("Austin, TX",)
    )
    assert _evaluate(_with_country("United States"), requirements).qualifies is True


def test_on_site_with_unknown_candidate_country_is_not_filtered():
    requirements = JobRequirements(
        remote_type=RemoteType.ON_SITE, locations=("Germany",)
    )
    assert _evaluate(_profile(), requirements).qualifies is True


def test_hybrid_location_is_soft_and_never_disqualifies():
    requirements = JobRequirements(
        remote_type=RemoteType.HYBRID, locations=("Germany",)
    )
    assert _evaluate(_with_country("United States"), requirements).qualifies is True


# ---- realistic mixed posting ---------------------------------------------------------


def test_posting_with_one_genuine_gate_among_a_wish_list_only_fails_that_gate():
    requirements = JobRequirements(
        degree_level=DegreeLevel.MASTERS,
        degree_required=False,  # soft — candidate lacks it, shouldn't matter
        remote_type=RemoteType.ON_SITE,
        locations=("Washington, DC",),  # hard, but same country — not a mismatch
        work_authorization=WorkAuthorizationStatus.CITIZEN,  # hard, and unmet
        min_years_experience=5,  # soft
        required_skills=("Python", "Kubernetes"),  # soft
    )
    profile = _profile(
        address=Address(country="United States"),
        address_source=ProvenanceSource.USER_ENTERED,
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.VISA_HOLDER,
            source=ProvenanceSource.USER_ENTERED,
        ),
    )

    result = _evaluate(profile, requirements)

    assert result.qualifies is False
    assert [item.category for item in result.failed] == [
        RequirementCategory.WORK_AUTHORIZATION
    ]
