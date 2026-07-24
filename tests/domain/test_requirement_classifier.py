"""Tests for RequirementClassifier — the mechanism that keeps a job
posting's wish-list requirements from over-filtering candidates by
splitting them into genuine hard disqualifiers vs soft preferences.
"""

from __future__ import annotations

from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.requirement_category import RequirementCategory
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)


def _classify(requirements: JobRequirements):
    return RequirementClassifier().classify(requirements)


# ---- empty input ----------------------------------------------------------------


def test_empty_requirements_yield_no_classifications():
    result = _classify(JobRequirements())
    assert result.hard == ()
    assert result.soft == ()


# ---- degree -----------------------------------------------------------------------


def test_required_degree_is_hard():
    result = _classify(
        JobRequirements(degree_level=DegreeLevel.BACHELORS, degree_required=True)
    )
    assert result.hard[0].category == RequirementCategory.DEGREE
    assert "Bachelor's degree required" in result.hard[0].description
    assert result.soft == ()


def test_preferred_degree_is_soft():
    result = _classify(
        JobRequirements(degree_level=DegreeLevel.MASTERS, degree_required=False)
    )
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.DEGREE
    assert "Master's degree preferred" in result.soft[0].description


def test_degree_with_unclear_requiredness_defaults_to_soft():
    result = _classify(JobRequirements(degree_level=DegreeLevel.BACHELORS))
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.DEGREE


# ---- clearance --------------------------------------------------------------------


def test_required_clearance_is_hard():
    result = _classify(
        JobRequirements(clearance_level=ClearanceLevel.SECRET, clearance_required=True)
    )
    assert result.hard[0].category == RequirementCategory.CLEARANCE
    assert "Secret clearance required" in result.hard[0].description
    assert result.soft == ()


def test_clearance_a_plus_is_soft():
    result = _classify(
        JobRequirements(
            clearance_level=ClearanceLevel.SECRET, clearance_required=False
        )
    )
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.CLEARANCE
    assert "preferred" in result.soft[0].description


# ---- location / remote --------------------------------------------------------------


def test_on_site_with_no_remote_option_is_hard():
    result = _classify(
        JobRequirements(remote_type=RemoteType.ON_SITE, locations=("New York, NY",))
    )
    assert result.hard[0].category == RequirementCategory.LOCATION
    assert "New York, NY" in result.hard[0].description
    assert result.soft == ()


def test_hybrid_location_preference_is_soft():
    result = _classify(
        JobRequirements(remote_type=RemoteType.HYBRID, locations=("Austin, TX",))
    )
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.LOCATION


def test_remote_location_preference_is_soft():
    result = _classify(
        JobRequirements(
            remote_type=RemoteType.REMOTE, locations=("United States",)
        )
    )
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.LOCATION


def test_location_with_unstated_remote_type_defaults_to_soft():
    result = _classify(JobRequirements(locations=("United States",)))
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.LOCATION


def test_no_locations_stated_produces_no_location_item():
    result = _classify(JobRequirements(remote_type=RemoteType.ON_SITE))
    assert result.hard == ()
    assert result.soft == ()


# ---- work authorization --------------------------------------------------------------


def test_citizenship_requirement_is_hard():
    result = _classify(
        JobRequirements(work_authorization=WorkAuthorizationStatus.CITIZEN)
    )
    assert result.hard[0].category == RequirementCategory.WORK_AUTHORIZATION
    assert result.soft == ()


def test_permanent_residency_requirement_is_hard():
    result = _classify(
        JobRequirements(
            work_authorization=WorkAuthorizationStatus.PERMANENT_RESIDENT
        )
    )
    assert result.hard[0].category == RequirementCategory.WORK_AUTHORIZATION
    assert result.soft == ()


def test_sponsorship_availability_is_soft_not_a_disqualifier():
    result = _classify(
        JobRequirements(
            work_authorization=WorkAuthorizationStatus.REQUIRES_SPONSORSHIP
        )
    )
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.WORK_AUTHORIZATION


def test_visa_holder_accepted_is_soft():
    result = _classify(
        JobRequirements(work_authorization=WorkAuthorizationStatus.VISA_HOLDER)
    )
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.WORK_AUTHORIZATION


# ---- experience / skills / preferences: always soft --------------------------------


def test_years_of_experience_is_always_soft():
    result = _classify(
        JobRequirements(min_years_experience=5, max_years_experience=8)
    )
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.EXPERIENCE
    assert result.soft[0].description == "5-8 years of experience"


def test_min_only_experience_reads_as_a_floor():
    result = _classify(JobRequirements(min_years_experience=5))
    assert result.soft[0].description == "5+ years of experience"


def test_required_skills_are_always_soft():
    result = _classify(
        JobRequirements(required_skills=("Python", "Kubernetes", "SQL"))
    )
    assert result.hard == ()
    assert [item.category for item in result.soft] == [RequirementCategory.SKILL] * 3
    assert [item.description for item in result.soft] == [
        "Python",
        "Kubernetes",
        "SQL",
    ]


def test_preferred_skills_are_soft_and_labeled():
    result = _classify(JobRequirements(preferred_skills=("Rust",)))
    assert result.hard == ()
    assert result.soft[0].description == "Rust (preferred)"


def test_free_text_preferences_are_soft():
    result = _classify(
        JobRequirements(preferences=("Startup experience a plus",))
    )
    assert result.hard == ()
    assert result.soft[0].category == RequirementCategory.PREFERENCE
    assert result.soft[0].description == "Startup experience a plus"


# ---- wish-list style descriptions (acceptance criterion 4) --------------------------


def test_typical_wish_list_posting_yields_no_hard_disqualifiers():
    """A posting written the way most job descriptions actually read:
    everything phrased as a nice-to-have, nothing an absolute cutoff.
    None of it should land in the hard set."""
    wish_list = JobRequirements(
        degree_level=DegreeLevel.MASTERS,
        degree_required=False,  # "Master's preferred"
        clearance_level=ClearanceLevel.SECRET,
        clearance_required=False,  # "Secret clearance a plus"
        remote_type=RemoteType.HYBRID,
        locations=("San Francisco, CA",),  # hybrid, so not a hard gate
        work_authorization=WorkAuthorizationStatus.REQUIRES_SPONSORSHIP,
        min_years_experience=5,  # "5+ years preferred"
        required_skills=("Python", "Kubernetes", "AWS", "Terraform"),
        preferred_skills=("Rust", "Go"),
        preferences=("Startup experience a plus", "Excellent communicator"),
    )

    result = _classify(wish_list)

    assert result.hard == ()
    assert len(result.soft) == 13


def test_posting_with_genuine_gates_mixed_into_a_wish_list():
    """The realistic case: a posting mixes a couple of genuine gates
    (citizenship, on-site) in among a pile of soft wish-list items. Only
    the genuine gates should land in the hard set."""
    mixed = JobRequirements(
        degree_level=DegreeLevel.BACHELORS,
        degree_required=True,  # genuine gate
        remote_type=RemoteType.ON_SITE,
        locations=("Washington, DC",),  # genuine gate: on-site, no remote
        work_authorization=WorkAuthorizationStatus.CITIZEN,  # genuine gate
        min_years_experience=3,  # wish-list
        required_skills=("Python",),  # wish-list
        preferences=("Nice to have: security clearance experience",),
    )

    result = _classify(mixed)

    assert {item.category for item in result.hard} == {
        RequirementCategory.DEGREE,
        RequirementCategory.LOCATION,
        RequirementCategory.WORK_AUTHORIZATION,
    }
    assert {item.category for item in result.soft} == {
        RequirementCategory.EXPERIENCE,
        RequirementCategory.SKILL,
        RequirementCategory.PREFERENCE,
    }
