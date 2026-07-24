"""Tests for SoftPreferenceEvaluator — decides which soft preferences a
candidate's profile meets vs. leaves as a gap, staying silent whenever
the profile has no data to judge either way.
"""

from __future__ import annotations

from datetime import date

from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.services.soft_preference_evaluator import SoftPreferenceEvaluator
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.remote_type import RemoteType

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


def _skill(name: str) -> Skill:
    return Skill(id=f"skill-{name}", name=name, source=ProvenanceSource.USER_ENTERED)


def _work_history(start: date, end: date | None = None) -> WorkHistoryEntry:
    return WorkHistoryEntry(
        id=f"job-{start.isoformat()}",
        company_name="Acme Corp",
        job_title="Software Engineer",
        start_date=start,
        end_date=end,
        source=ProvenanceSource.USER_ENTERED,
    )


def _evaluate(profile: UserProfile, requirements: JobRequirements):
    return SoftPreferenceEvaluator().evaluate(profile, requirements, as_of=_AS_OF)


# ---- nothing soft to evaluate ------------------------------------------------------


def test_empty_requirements_yield_no_evaluation():
    result = _evaluate(_profile(), JobRequirements())
    assert result.met == ()
    assert result.gaps == ()


def test_hard_requirements_are_never_evaluated_here():
    """Only categories RequirementClassifier puts in `soft` are ever
    touched — a required (hard) degree must never show up as met or a gap."""
    requirements = JobRequirements(
        degree_level=DegreeLevel.BACHELORS, degree_required=True
    )
    result = _evaluate(_profile(highest_degree=DegreeLevel.MASTERS), requirements)
    assert result.met == ()
    assert result.gaps == ()


# ---- degree -----------------------------------------------------------------------


def test_preferred_degree_met():
    requirements = JobRequirements(
        degree_level=DegreeLevel.BACHELORS, degree_required=False
    )
    result = _evaluate(_profile(highest_degree=DegreeLevel.MASTERS), requirements)
    assert len(result.met) == 1
    assert result.gaps == ()


def test_preferred_degree_gap():
    requirements = JobRequirements(
        degree_level=DegreeLevel.MASTERS, degree_required=False
    )
    result = _evaluate(_profile(highest_degree=DegreeLevel.BACHELORS), requirements)
    assert result.met == ()
    assert len(result.gaps) == 1


def test_preferred_degree_unknown_is_neither_met_nor_a_gap():
    requirements = JobRequirements(
        degree_level=DegreeLevel.BACHELORS, degree_required=False
    )
    result = _evaluate(_profile(), requirements)
    assert result.met == ()
    assert result.gaps == ()


# ---- clearance --------------------------------------------------------------------


def test_preferred_clearance_met():
    requirements = JobRequirements(
        clearance_level=ClearanceLevel.SECRET, clearance_required=False
    )
    result = _evaluate(
        _profile(clearance_level=ClearanceLevel.TOP_SECRET), requirements
    )
    assert len(result.met) == 1
    assert result.gaps == ()


def test_preferred_clearance_gap():
    requirements = JobRequirements(
        clearance_level=ClearanceLevel.TOP_SECRET, clearance_required=False
    )
    result = _evaluate(_profile(clearance_level=ClearanceLevel.SECRET), requirements)
    assert result.met == ()
    assert len(result.gaps) == 1


def test_preferred_clearance_unknown_is_neither_met_nor_a_gap():
    requirements = JobRequirements(
        clearance_level=ClearanceLevel.SECRET, clearance_required=False
    )
    result = _evaluate(_profile(), requirements)
    assert result.met == ()
    assert result.gaps == ()


# ---- skills -----------------------------------------------------------------------


def test_required_and_preferred_skills_split_by_profile_match():
    requirements = JobRequirements(
        required_skills=("Python", "Kubernetes"),
        preferred_skills=("Rust",),
    )
    profile = _profile(skills=[_skill("Python"), _skill("Go")])

    result = _evaluate(profile, requirements)

    assert {item.description for item in result.met} == {"Python"}
    assert {item.description for item in result.gaps} == {
        "Kubernetes",
        "Rust (preferred)",
    }


def test_skill_matching_is_case_insensitive():
    requirements = JobRequirements(required_skills=("python",))
    profile = _profile(skills=[_skill("Python")])

    result = _evaluate(profile, requirements)

    assert len(result.met) == 1
    assert result.gaps == ()


def test_no_skills_on_profile_means_every_required_skill_is_a_gap():
    requirements = JobRequirements(required_skills=("Python",))
    result = _evaluate(_profile(), requirements)
    assert result.met == ()
    assert len(result.gaps) == 1


# ---- experience --------------------------------------------------------------------


def test_experience_met_when_total_tenure_meets_the_floor():
    requirements = JobRequirements(min_years_experience=5)
    profile = _profile(
        work_history=[_work_history(date(2018, 1, 1), date(2026, 1, 1))]
    )
    result = _evaluate(profile, requirements)
    assert len(result.met) == 1
    assert result.gaps == ()


def test_experience_gap_when_total_tenure_falls_short():
    requirements = JobRequirements(min_years_experience=8)
    profile = _profile(
        work_history=[_work_history(date(2023, 1, 1), date(2026, 1, 1))]
    )
    result = _evaluate(profile, requirements)
    assert result.met == ()
    assert len(result.gaps) == 1


def test_open_ended_role_counts_through_as_of():
    requirements = JobRequirements(min_years_experience=5)
    profile = _profile(work_history=[_work_history(date(2018, 1, 1), None)])
    result = _evaluate(profile, requirements)
    assert len(result.met) == 1


def test_no_work_history_means_experience_is_neither_met_nor_a_gap():
    requirements = JobRequirements(min_years_experience=5)
    result = _evaluate(_profile(), requirements)
    assert result.met == ()
    assert result.gaps == ()


# ---- realistic mixed posting ---------------------------------------------------------


def test_wish_list_posting_split_into_met_and_gaps():
    requirements = JobRequirements(
        degree_level=DegreeLevel.MASTERS,
        degree_required=False,
        remote_type=RemoteType.HYBRID,
        locations=("Austin, TX",),
        min_years_experience=5,
        required_skills=("Python", "Kubernetes"),
        preferred_skills=("Rust",),
    )
    profile = _profile(
        highest_degree=DegreeLevel.BACHELORS,  # below preferred -> gap
        skills=[_skill("Python")],  # Kubernetes/Rust -> gaps
        work_history=[_work_history(date(2015, 1, 1), date(2026, 1, 1))],  # meets 5+
    )

    result = _evaluate(profile, requirements)

    assert {item.description for item in result.met} == {
        "Python",
        "5+ years of experience",
    }
    assert {item.description for item in result.gaps} == {
        "Master's degree preferred",
        "Kubernetes",
        "Rust (preferred)",
    }
