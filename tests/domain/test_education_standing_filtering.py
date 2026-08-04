"""Tests for education standing and the honest degree comparison it enables.

The defect these exist for
--------------------------
`highest_degree` means highest *completed* degree, so a current undergraduate's
truthful answer is "high school" — which disqualified them from most new-grad
roles and a great many internships, where "bachelor's required" means *in
progress*. The only way to get the right postings was to claim a degree they had
not finished.

So the cases that matter here are: an in-progress degree counts, except when the
posting says it must be finished; and a standing requirement can rule someone out
that a degree comparison never could.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import InvalidValueError
from src.domain.services.hard_disqualifier_filter import HardDisqualifierFilter
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.education_standing import (
    EducationStanding,
    EnrollmentStatus,
)
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.student_status_requirement import (
    StudentStatusRequirement,
)

PURSUING_BACHELORS = EducationStanding(
    enrollment_status=EnrollmentStatus.UNDERGRADUATE,
    degree_in_progress=DegreeLevel.BACHELORS,
    expected_graduation=date(2027, 5, 15),
)
PURSUING_MASTERS = EducationStanding(
    enrollment_status=EnrollmentStatus.GRADUATE,
    degree_in_progress=DegreeLevel.MASTERS,
)


def _profile(
    *,
    highest_degree: DegreeLevel | None = None,
    standing: EducationStanding | None = None,
) -> UserProfile:
    profile = UserProfile(
        id="p1",
        user_id="u1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    profile.highest_degree = highest_degree
    if standing is not None:
        profile.set_education_standing(standing)
    return profile


def _qualifies(profile: UserProfile, requirements: JobRequirements) -> bool:
    return HardDisqualifierFilter().evaluate(profile, requirements).qualifies


_BACHELORS_REQUIRED = JobRequirements(
    degree_level=DegreeLevel.BACHELORS, degree_required=True
)


# -- The value object's own rules ----------------------------------------------


def test_unanswered_and_not_enrolled_are_different_states() -> None:
    """The reason `enrollment_status` is optional rather than defaulting. "I have
    finished studying" is a fact filtering may act on; "I have not said" must never
    cost a posting, and an enum member alone cannot express the second."""
    assert not EducationStanding().is_stated
    assert EducationStanding(enrollment_status=EnrollmentStatus.NOT_ENROLLED).is_stated
    assert EducationStanding(enrollment_status=EnrollmentStatus.UNDERGRADUATE).is_stated

    assert not EducationStanding().is_enrolled
    assert not EducationStanding(
        enrollment_status=EnrollmentStatus.NOT_ENROLLED
    ).is_enrolled


def test_not_enrolled_alongside_a_degree_in_progress_is_refused() -> None:
    """A contradiction the candidate meant one half of. Guessing which would
    store an answer they did not give."""
    with pytest.raises(InvalidValueError):
        EducationStanding(
            enrollment_status=EnrollmentStatus.NOT_ENROLLED,
            degree_in_progress=DegreeLevel.BACHELORS,
        )
    with pytest.raises(InvalidValueError):
        EducationStanding(
            enrollment_status=EnrollmentStatus.NOT_ENROLLED,
            expected_graduation=date(2027, 5, 1),
        )


def test_enrolled_through_is_three_valued_not_boolean() -> None:
    """ "Cannot tell" must not collapse into "no"."""
    assert PURSUING_BACHELORS.is_enrolled_through(date(2027, 1, 1)) is True
    assert PURSUING_BACHELORS.is_enrolled_through(date(2028, 1, 1)) is False
    # Enrolled but no date given, and not enrolled at all: both unknown.
    assert PURSUING_MASTERS.is_enrolled_through(date(2027, 1, 1)) is None
    assert EducationStanding().is_enrolled_through(date(2027, 1, 1)) is None


# -- The degree comparison this phase fixes ------------------------------------


def test_an_undergraduate_pursuing_a_bachelors_qualifies_for_a_bachelors_role() -> None:
    """The defect, stated as a test. Their highest *completed* degree is nothing;
    what they are working towards is what the posting means."""
    profile = _profile(standing=PURSUING_BACHELORS)

    assert _qualifies(profile, _BACHELORS_REQUIRED)


def test_the_same_candidate_without_this_section_still_qualifies() -> None:
    """Unstated remains unstated: an empty profile is never disqualified, which is
    why this fix adds a fact rather than changing what silence means."""
    assert _qualifies(_profile(), _BACHELORS_REQUIRED)


def test_an_undergraduate_is_still_disqualified_from_a_masters_role() -> None:
    """The other half of the goal. Pursuing a bachelor's must not open Master's-
    and PhD-only postings."""
    profile = _profile(standing=PURSUING_BACHELORS)

    assert not _qualifies(
        profile,
        JobRequirements(degree_level=DegreeLevel.MASTERS, degree_required=True),
    )


def test_a_posting_demanding_a_finished_degree_ignores_one_in_progress() -> None:
    """`GRADUATED` is the posting saying an in-progress degree does not count, and
    is the reason the degree check has to read the standing requirement.

    The candidate here has *stated* a completed level (high school), which is what
    makes the mismatch provable. With no completed degree on file at all the
    posting still shows — see the test below, which pins that deliberately.
    """
    profile = _profile(
        highest_degree=DegreeLevel.HIGH_SCHOOL, standing=PURSUING_BACHELORS
    )

    assert not _qualifies(
        profile,
        JobRequirements(
            degree_level=DegreeLevel.BACHELORS,
            degree_required=True,
            student_status_requirement=StudentStatusRequirement.GRADUATED,
        ),
    )


def test_a_completed_degree_satisfies_a_graduated_posting() -> None:
    profile = _profile(
        highest_degree=DegreeLevel.BACHELORS, standing=EducationStanding()
    )

    assert _qualifies(
        profile,
        JobRequirements(
            degree_level=DegreeLevel.BACHELORS,
            degree_required=True,
            student_status_requirement=StudentStatusRequirement.GRADUATED,
        ),
    )


def test_the_higher_of_completed_and_in_progress_is_used() -> None:
    """A master's student who already holds a bachelor's meets a bachelor's
    requirement on either count; the comparison must not pick the lower."""
    profile = _profile(highest_degree=DegreeLevel.BACHELORS, standing=PURSUING_MASTERS)

    assert _qualifies(profile, _BACHELORS_REQUIRED)
    assert _qualifies(
        profile,
        JobRequirements(degree_level=DegreeLevel.MASTERS, degree_required=True),
    )


def test_a_preferred_degree_never_disqualifies_regardless_of_standing() -> None:
    """Only `degree_required` postings are hard, and this phase did not change
    that."""
    profile = _profile(standing=PURSUING_BACHELORS)

    assert _qualifies(
        profile,
        JobRequirements(degree_level=DegreeLevel.DOCTORATE, degree_required=False),
    )


# -- Standing requirements ------------------------------------------------------


def test_a_graduate_student_only_internship_excludes_an_undergraduate() -> None:
    """The case that was unfilterable in principle before: two internships can
    both say "bachelor's" and mean opposite things about who may apply."""
    profile = _profile(standing=PURSUING_BACHELORS)

    result = HardDisqualifierFilter().evaluate(
        profile,
        JobRequirements(
            student_status_requirement=(
                StudentStatusRequirement.CURRENT_GRADUATE_STUDENT
            )
        ),
    )

    assert not result.qualifies
    assert "graduate student" in result.failed[0].description


def test_the_same_internship_accepts_a_masters_student() -> None:
    profile = _profile(standing=PURSUING_MASTERS)

    assert _qualifies(
        profile,
        JobRequirements(
            student_status_requirement=(
                StudentStatusRequirement.CURRENT_GRADUATE_STUDENT
            )
        ),
    )


def test_a_graduated_posting_still_shows_when_no_completed_degree_is_stated() -> None:
    """Deliberate, and the boundary of the previous test. An unset
    `highest_degree` does not prove the candidate has never graduated — they may
    simply not have filled it in — and this filter only ever removes a posting on
    a provable mismatch."""
    profile = _profile(standing=PURSUING_BACHELORS)

    assert _qualifies(
        profile,
        JobRequirements(
            degree_level=DegreeLevel.BACHELORS,
            degree_required=True,
            student_status_requirement=StudentStatusRequirement.GRADUATED,
        ),
    )


def test_a_current_student_requirement_excludes_someone_who_said_they_finished() -> (
    None
):
    """Now expressible, and it was not before: a stated `NOT_ENROLLED` is an
    answer, so a student-only posting can be filtered out for someone who has
    graduated."""
    profile = _profile(
        highest_degree=DegreeLevel.BACHELORS,
        standing=EducationStanding(enrollment_status=EnrollmentStatus.NOT_ENROLLED),
    )

    result = HardDisqualifierFilter().evaluate(
        profile,
        JobRequirements(
            student_status_requirement=StudentStatusRequirement.CURRENT_STUDENT
        ),
    )

    assert not result.qualifies
    assert "current student" in result.failed[0].description


def test_an_undergraduate_only_role_excludes_a_graduate_student() -> None:
    profile = _profile(standing=PURSUING_MASTERS)

    assert not _qualifies(
        profile,
        JobRequirements(
            student_status_requirement=(StudentStatusRequirement.CURRENT_UNDERGRADUATE)
        ),
    )


def test_a_candidate_who_said_nothing_is_never_ruled_out_by_standing() -> None:
    for required in StudentStatusRequirement:
        assert _qualifies(
            _profile(), JobRequirements(student_status_requirement=required)
        ), required


def test_a_standing_requirement_is_always_hard_never_a_preference() -> None:
    """There is no soft version: "must be currently enrolled" is a rule about who
    may apply, usually because the programme is funded for students."""
    from src.domain.services.requirement_classifier import RequirementClassifier
    from src.domain.value_objects.requirement_category import RequirementCategory

    classification = RequirementClassifier().classify(
        JobRequirements(
            student_status_requirement=StudentStatusRequirement.CURRENT_STUDENT
        )
    )

    assert [item.category for item in classification.hard] == [
        RequirementCategory.ELIGIBILITY
    ]
    assert classification.soft == ()
