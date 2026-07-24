import pytest

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.remote_type import RemoteType


def test_all_fields_optional_by_default():
    requirements = JobRequirements()
    assert requirements.degree_level is None
    assert requirements.clearance_level is None
    assert requirements.remote_type is None
    assert requirements.locations == ()
    assert requirements.work_authorization is None
    assert requirements.min_years_experience is None
    assert requirements.max_years_experience is None
    assert requirements.required_skills == ()
    assert requirements.preferred_skills == ()
    assert requirements.preferences == ()


def test_constructs_with_a_full_set_of_attributes():
    requirements = JobRequirements(
        degree_level=DegreeLevel.BACHELORS,
        degree_required=True,
        remote_type=RemoteType.REMOTE,
        locations=("United States",),
        min_years_experience=3,
        max_years_experience=6,
        required_skills=("Python", "SQL"),
        preferred_skills=("Kubernetes",),
        preferences=("Startup experience a plus",),
    )
    assert requirements.degree_level == DegreeLevel.BACHELORS
    assert requirements.min_years_experience == 3
    assert requirements.required_skills == ("Python", "SQL")


def test_negative_min_years_experience_rejected():
    with pytest.raises(InvalidValueError):
        JobRequirements(min_years_experience=-1)


def test_negative_max_years_experience_rejected():
    with pytest.raises(InvalidValueError):
        JobRequirements(max_years_experience=-1)


def test_min_years_greater_than_max_years_rejected():
    with pytest.raises(InvalidValueError):
        JobRequirements(min_years_experience=8, max_years_experience=3)


def test_equal_min_and_max_years_is_allowed():
    requirements = JobRequirements(min_years_experience=5, max_years_experience=5)
    assert requirements.min_years_experience == 5
    assert requirements.max_years_experience == 5
