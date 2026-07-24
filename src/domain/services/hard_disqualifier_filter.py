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
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.requirement_category import RequirementCategory
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
    def _check_degree(
        profile: UserProfile,
        requirements: JobRequirements,
        failed: list[ClassifiedRequirement],
    ) -> None:
        required_level = requirements.degree_level
        candidate_level = profile.highest_degree
        if required_level is None or candidate_level is None:
            return
        if _DEGREE_RANK[candidate_level] < _DEGREE_RANK[required_level]:
            failed.append(
                ClassifiedRequirement(
                    category=RequirementCategory.DEGREE,
                    description=f"Requires {_DEGREE_LABELS[required_level]}",
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
