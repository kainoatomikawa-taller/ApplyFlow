"""HardDisqualifierFilter — a pure domain service that decides whether a
candidate's `UserProfile` genuinely fails a job posting's hard
disqualifiers (see `RequirementClassifier`).

Only the categories `RequirementClassifier` has already put in the hard
set are ever checked here — this service never re-derives which
attributes count as a genuine gate, it only compares the candidate's
profile against the ones the classifier already decided are non-negotiable.
That keeps "what counts as hard" defined in exactly one place.

Every comparison defaults to *qualified* whenever the profile doesn't
state the relevant fact (no held clearance recorded, no degree recorded,
no country on file) — an unstated fact is unknown, not a failure, and
guessing it into a disqualification is exactly the over-filtering this
service exists to avoid. A job is only ever excluded when the profile
affirmatively states a fact that conflicts with the posting's hard
requirement.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities.user_profile import UserProfile
from src.domain.services.requirement_classifier import (
    ClassifiedRequirement,
    RequirementClassifier,
)
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.education_standing import EnrollmentStatus
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.requirement_category import RequirementCategory
from src.domain.value_objects.student_status_requirement import (
    ENROLLMENT_REQUIRING,
    StudentStatusRequirement,
)
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)

_DEGREE_RANK: dict[DegreeLevel, int] = {
    DegreeLevel.HIGH_SCHOOL: 0,
    DegreeLevel.ASSOCIATE: 1,
    DegreeLevel.BACHELORS: 2,
    DegreeLevel.MASTERS: 3,
    DegreeLevel.DOCTORATE: 4,
}

_CLEARANCE_RANK: dict[ClearanceLevel, int] = {
    ClearanceLevel.PUBLIC_TRUST: 0,
    ClearanceLevel.CONFIDENTIAL: 1,
    ClearanceLevel.SECRET: 2,
    ClearanceLevel.TOP_SECRET: 3,
    ClearanceLevel.TOP_SECRET_SCI: 4,
}

_DEGREE_LABELS: dict[DegreeLevel, str] = {
    DegreeLevel.HIGH_SCHOOL: "a high school diploma",
    DegreeLevel.ASSOCIATE: "an Associate degree",
    DegreeLevel.BACHELORS: "a Bachelor's degree",
    DegreeLevel.MASTERS: "a Master's degree",
    DegreeLevel.DOCTORATE: "a Doctorate",
}

_CLEARANCE_LABELS: dict[ClearanceLevel, str] = {
    ClearanceLevel.PUBLIC_TRUST: "a Public Trust clearance",
    ClearanceLevel.CONFIDENTIAL: "a Confidential clearance",
    ClearanceLevel.SECRET: "a Secret clearance",
    ClearanceLevel.TOP_SECRET: "a Top Secret clearance",
    ClearanceLevel.TOP_SECRET_SCI: "a Top Secret/SCI clearance",
}

#: Country name variants that should be treated as the same country when
#: comparing a candidate's address against a job's stated location. Only
#: covers the aliasing actually needed for this comparison, not a general
#: country database.
_COUNTRY_ALIASES: dict[str, frozenset[str]] = {
    "united states": frozenset(
        {
            "united states",
            "united states of america",
            "usa",
            "u.s.",
            "u.s.a.",
            "us",
        }
    ),
}


def _canonical_country(text: str) -> str | None:
    """Return a normalized country name for `text`, or None if it doesn't
    confidently read as a bare country name.

    A job's `locations` entries are free text (see `JobRequirements`):
    country-level statements read as a single token ("United States",
    "Canada"), while city/region statements conventionally carry a comma
    ("New York, NY", "Austin, TX"). Treating anything comma-separated as
    "not a confident country signal" keeps city-level text from being
    misread as a country mismatch — the near-miss protection this filter
    is built around.
    """
    normalized = text.strip().lower()
    if not normalized or "," in normalized:
        return None
    for canonical, aliases in _COUNTRY_ALIASES.items():
        if normalized in aliases:
            return canonical
    return normalized


_STUDENT_STATUS_LABELS: dict[StudentStatusRequirement, str] = {
    StudentStatusRequirement.CURRENT_STUDENT: "Requires being a current student",
    StudentStatusRequirement.CURRENT_UNDERGRADUATE: (
        "Requires being a current undergraduate"
    ),
    StudentStatusRequirement.CURRENT_GRADUATE_STUDENT: (
        "Requires being a current graduate student"
    ),
    StudentStatusRequirement.GRADUATED: "Requires having already graduated",
}


def _highest_of(
    completed: DegreeLevel | None, in_progress: DegreeLevel | None
) -> DegreeLevel | None:
    """The higher of a finished and an in-progress degree, or whichever exists.

    Used where a posting accepts a degree in progress, which is the normal case
    for internships and new-grad roles. `max` on the rank rather than on the enum:
    `DegreeLevel` is a `StrEnum`, so comparing members directly would compare
    their *names* alphabetically and rank "doctorate" below "high_school".
    """
    present = [level for level in (completed, in_progress) if level is not None]
    if not present:
        return None
    return max(present, key=lambda level: _DEGREE_RANK[level])


@dataclass(frozen=True)
class HardDisqualifierResult:
    """Whether a candidate qualifies against a job's hard disqualifiers,
    and which ones (if any) they failed."""

    qualifies: bool
    failed: tuple[ClassifiedRequirement, ...] = ()


class HardDisqualifierFilter:
    """Checks a `UserProfile` against a job's `JobRequirements`, gating
    only on the categories `RequirementClassifier` has already classified
    as hard disqualifiers."""

    def __init__(self, classifier: RequirementClassifier | None = None) -> None:
        self._classifier = classifier or RequirementClassifier()

    def evaluate(
        self, profile: UserProfile, requirements: JobRequirements
    ) -> HardDisqualifierResult:
        hard_categories = {
            item.category for item in self._classifier.classify(requirements).hard
        }
        failed: list[ClassifiedRequirement] = []

        if RequirementCategory.ELIGIBILITY in hard_categories:
            self._check_student_status(profile, requirements, failed)
        if RequirementCategory.DEGREE in hard_categories:
            self._check_degree(profile, requirements, failed)
        if RequirementCategory.CLEARANCE in hard_categories:
            self._check_clearance(profile, requirements, failed)
        if RequirementCategory.LOCATION in hard_categories:
            self._check_location(profile, requirements, failed)
        if RequirementCategory.WORK_AUTHORIZATION in hard_categories:
            self._check_work_authorization(profile, requirements, failed)

        return HardDisqualifierResult(qualifies=not failed, failed=tuple(failed))

    @staticmethod
    def _check_student_status(
        profile: UserProfile,
        requirements: JobRequirements,
        failed: list[ClassifiedRequirement],
    ) -> None:
        """Refuse a posting whose standing requirement the candidate provably
        fails.

        This is the check that separates an undergraduate internship from a
        PhD-only one — postings that say the same thing about degrees and
        opposite things about who may apply.

        A candidate who has said nothing about their standing is left alone, the
        same way an unset clearance or degree is: `EducationStanding` defaults to
        `NOT_ENROLLED`, which is indistinguishable from "not asked yet", so
        treating it as a statement would disqualify every profile that has never
        opened the section.
        """
        required = requirements.student_status_requirement
        standing = profile.education_standing
        if required is None or not standing.is_stated:
            return

        if required is StudentStatusRequirement.GRADUATED:
            # Enrolment is irrelevant here; the degree check below is what
            # enforces this one, against completed degrees only.
            return

        if required in ENROLLMENT_REQUIRING and not standing.is_enrolled:
            failed.append(
                ClassifiedRequirement(
                    category=RequirementCategory.ELIGIBILITY,
                    description=_STUDENT_STATUS_LABELS[required],
                )
            )
            return

        wrong_level = (
            required is StudentStatusRequirement.CURRENT_UNDERGRADUATE
            and standing.enrollment_status is not EnrollmentStatus.UNDERGRADUATE
        ) or (
            required is StudentStatusRequirement.CURRENT_GRADUATE_STUDENT
            and standing.enrollment_status is not EnrollmentStatus.GRADUATE
        )
        if wrong_level:
            failed.append(
                ClassifiedRequirement(
                    category=RequirementCategory.ELIGIBILITY,
                    description=_STUDENT_STATUS_LABELS[required],
                )
            )

    @staticmethod
    def _check_degree(
        profile: UserProfile,
        requirements: JobRequirements,
        failed: list[ClassifiedRequirement],
    ) -> None:
        """Compare the posting's degree requirement against what the candidate
        has finished — or is working towards, when the posting allows it.

        The in-progress half is the honest fix for a real defect. A current
        undergraduate's highest *completed* degree is a high-school diploma, so
        comparing that against "bachelor's required" disqualified them from most
        new-grad roles and a great many internships — where "bachelor's required"
        means *in progress*. The only way to get the right postings used to be to
        claim a degree they had not finished.

        A posting demanding `GRADUATED` is the case where an in-progress degree
        must not count, and is why this method reads
        `student_status_requirement` rather than degrees alone.
        """
        required_level = requirements.degree_level
        if required_level is None:
            return

        completed = profile.highest_degree
        in_progress = profile.education_standing.degree_in_progress
        must_be_finished = (
            requirements.student_status_requirement
            is StudentStatusRequirement.GRADUATED
        )
        candidate_level = (
            completed if must_be_finished else _highest_of(completed, in_progress)
        )
        if candidate_level is None:
            return
        if _DEGREE_RANK[candidate_level] < _DEGREE_RANK[required_level]:
            failed.append(
                ClassifiedRequirement(
                    category=RequirementCategory.DEGREE,
                    description=(
                        f"Requires a completed {_DEGREE_LABELS[required_level]}"
                        if must_be_finished
                        else f"Requires {_DEGREE_LABELS[required_level]}"
                    ),
                )
            )

    @staticmethod
    def _check_clearance(
        profile: UserProfile,
        requirements: JobRequirements,
        failed: list[ClassifiedRequirement],
    ) -> None:
        required_level = requirements.clearance_level
        candidate_level = profile.clearance_level
        if required_level is None or candidate_level is None:
            return
        if _CLEARANCE_RANK[candidate_level] < _CLEARANCE_RANK[required_level]:
            failed.append(
                ClassifiedRequirement(
                    category=RequirementCategory.CLEARANCE,
                    description=f"Requires {_CLEARANCE_LABELS[required_level]}",
                )
            )

    @staticmethod
    def _check_location(
        profile: UserProfile,
        requirements: JobRequirements,
        failed: list[ClassifiedRequirement],
    ) -> None:
        if requirements.remote_type != RemoteType.ON_SITE or not requirements.locations:
            return

        profile_country = profile.address.country
        if not profile_country:
            return
        candidate_country = _canonical_country(profile_country)
        if candidate_country is None:
            return

        job_countries = {
            country
            for location in requirements.locations
            if (country := _canonical_country(location)) is not None
        }
        if not job_countries:
            return
        if candidate_country in job_countries:
            return

        where = ", ".join(requirements.locations)
        failed.append(
            ClassifiedRequirement(
                category=RequirementCategory.LOCATION,
                description=f"On-site in {where}, outside candidate's country",
            )
        )

    @staticmethod
    def _check_work_authorization(
        profile: UserProfile,
        requirements: JobRequirements,
        failed: list[ClassifiedRequirement],
    ) -> None:
        required_status = requirements.work_authorization
        if required_status not in (
            WorkAuthorizationStatus.CITIZEN,
            WorkAuthorizationStatus.PERMANENT_RESIDENT,
        ):
            return
        if profile.work_authorization is None:
            return

        candidate_status = profile.work_authorization.status
        if required_status == WorkAuthorizationStatus.CITIZEN:
            satisfied = candidate_status == WorkAuthorizationStatus.CITIZEN
        else:
            satisfied = candidate_status in (
                WorkAuthorizationStatus.CITIZEN,
                WorkAuthorizationStatus.PERMANENT_RESIDENT,
            )
        if not satisfied:
            failed.append(
                ClassifiedRequirement(
                    category=RequirementCategory.WORK_AUTHORIZATION,
                    description=(
                        "Requires U.S. citizenship"
                        if required_status == WorkAuthorizationStatus.CITIZEN
                        else "Requires permanent residency or citizenship"
                    ),
                )
            )
