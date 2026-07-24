"""RequirementClassifier — a pure domain service that splits a job
posting's parsed `JobRequirements` into hard disqualifiers and soft
preferences.

Job descriptions are wish-lists: most of what they state is negotiable,
and treating every stated attribute as a hard cutoff causes over-filtering
(a strong candidate gets auto-rejected over a "nice to have"). This
service is the mechanism that prevents that — it draws the line between
the small set of attributes that genuinely gate eligibility (a stated
minimum degree that's actually required, a required clearance, an
on-site-only location with no remote option, a work-authorization status
that excludes visa/sponsorship candidates) and everything else, which
never disqualifies regardless of how the posting words it ("required",
"must have", "5+ years") — years of experience, every skill (required or
preferred alike), and any other stated preference always land in the soft
set. See `RequirementCategory` for the fixed set of categories that can
ever be hard.

Ambiguous signals resolve toward soft, not hard: a degree/clearance whose
`*_required` flag is `None` (the extractor couldn't tell), or a location
constraint paired with an unstated `remote_type`, is treated as a
preference rather than guessed into a disqualifier — consistent with
`JobRequirements`' own "never invent" discipline.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.requirement_category import RequirementCategory
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)

#: Employer-stated minimum authorization statuses that actually exclude
#: candidates (a citizenship/PR gate). Every other status the extractor
#: can produce — VISA_HOLDER, REQUIRES_SPONSORSHIP, OTHER, NOT_AUTHORIZED
#: (nonsensical as an employer-stated minimum, but handled the same way) —
#: is either permissive (sponsorship being offered) or too ambiguous to
#: treat as a disqualifier.
_HARD_WORK_AUTHORIZATION_STATUSES = frozenset(
    {WorkAuthorizationStatus.CITIZEN, WorkAuthorizationStatus.PERMANENT_RESIDENT}
)

_DEGREE_LABELS: dict[DegreeLevel, str] = {
    DegreeLevel.HIGH_SCHOOL: "High school diploma",
    DegreeLevel.ASSOCIATE: "Associate degree",
    DegreeLevel.BACHELORS: "Bachelor's degree",
    DegreeLevel.MASTERS: "Master's degree",
    DegreeLevel.DOCTORATE: "Doctorate",
}

_CLEARANCE_LABELS: dict[ClearanceLevel, str] = {
    ClearanceLevel.PUBLIC_TRUST: "Public Trust clearance",
    ClearanceLevel.CONFIDENTIAL: "Confidential clearance",
    ClearanceLevel.SECRET: "Secret clearance",
    ClearanceLevel.TOP_SECRET: "Top Secret clearance",
    ClearanceLevel.TOP_SECRET_SCI: "Top Secret/SCI clearance",
}

_WORK_AUTHORIZATION_LABELS: dict[WorkAuthorizationStatus, str] = {
    WorkAuthorizationStatus.CITIZEN: "U.S. citizenship",
    WorkAuthorizationStatus.PERMANENT_RESIDENT: "permanent residency or citizenship",
    WorkAuthorizationStatus.VISA_HOLDER: "an existing work visa",
    WorkAuthorizationStatus.REQUIRES_SPONSORSHIP: "visa sponsorship availability",
    WorkAuthorizationStatus.NOT_AUTHORIZED: "an unspecified authorization status",
    WorkAuthorizationStatus.OTHER: "an unspecified authorization status",
}


@dataclass(frozen=True)
class ClassifiedRequirement:
    """One attribute of a `JobRequirements`, tagged with the category it
    came from and a human-readable description."""

    category: RequirementCategory
    description: str


@dataclass(frozen=True)
class RequirementClassification:
    """The result of splitting a `JobRequirements` in two: `hard`
    disqualifiers a candidate must clear, and `soft` preferences that
    should never by themselves cause a rejection."""

    hard: tuple[ClassifiedRequirement, ...] = ()
    soft: tuple[ClassifiedRequirement, ...] = ()


class RequirementClassifier:
    """Splits a job posting's `JobRequirements` into hard disqualifiers
    and soft preferences."""

    def classify(self, requirements: JobRequirements) -> RequirementClassification:
        hard: list[ClassifiedRequirement] = []
        soft: list[ClassifiedRequirement] = []

        self._classify_degree(requirements, hard, soft)
        self._classify_clearance(requirements, hard, soft)
        self._classify_location(requirements, hard, soft)
        self._classify_work_authorization(requirements, hard, soft)
        self._classify_experience(requirements, soft)
        self._classify_skills(requirements, soft)
        self._classify_preferences(requirements, soft)

        return RequirementClassification(hard=tuple(hard), soft=tuple(soft))

    @staticmethod
    def _classify_degree(
        requirements: JobRequirements,
        hard: list[ClassifiedRequirement],
        soft: list[ClassifiedRequirement],
    ) -> None:
        if requirements.degree_level is None:
            return
        label = _DEGREE_LABELS[requirements.degree_level]
        item = ClassifiedRequirement(
            category=RequirementCategory.DEGREE,
            description=f"{label} required"
            if requirements.degree_required
            else f"{label} preferred",
        )
        (hard if requirements.degree_required else soft).append(item)

    @staticmethod
    def _classify_clearance(
        requirements: JobRequirements,
        hard: list[ClassifiedRequirement],
        soft: list[ClassifiedRequirement],
    ) -> None:
        if requirements.clearance_level is None:
            return
        label = _CLEARANCE_LABELS[requirements.clearance_level]
        item = ClassifiedRequirement(
            category=RequirementCategory.CLEARANCE,
            description=f"{label} required"
            if requirements.clearance_required
            else f"{label} preferred",
        )
        (hard if requirements.clearance_required else soft).append(item)

    @staticmethod
    def _classify_location(
        requirements: JobRequirements,
        hard: list[ClassifiedRequirement],
        soft: list[ClassifiedRequirement],
    ) -> None:
        if not requirements.locations:
            return
        where = ", ".join(requirements.locations)
        # Only an on-site posting with no remote option turns a location
        # constraint into a genuine disqualifier. A stated REMOTE/HYBRID
        # option — or an unstated remote_type, which the extractor
        # couldn't confirm either way — leaves candidates elsewhere still
        # eligible, so the constraint is only ever a preference there.
        if requirements.remote_type == RemoteType.ON_SITE:
            hard.append(
                ClassifiedRequirement(
                    category=RequirementCategory.LOCATION,
                    description=f"On-site in {where}, no remote option",
                )
            )
        else:
            soft.append(
                ClassifiedRequirement(
                    category=RequirementCategory.LOCATION,
                    description=f"Prefers candidates in {where}",
                )
            )

    @staticmethod
    def _classify_work_authorization(
        requirements: JobRequirements,
        hard: list[ClassifiedRequirement],
        soft: list[ClassifiedRequirement],
    ) -> None:
        status = requirements.work_authorization
        if status is None:
            return
        label = _WORK_AUTHORIZATION_LABELS[status]
        if status in _HARD_WORK_AUTHORIZATION_STATUSES:
            hard.append(
                ClassifiedRequirement(
                    category=RequirementCategory.WORK_AUTHORIZATION,
                    description=f"Requires {label}",
                )
            )
        else:
            soft.append(
                ClassifiedRequirement(
                    category=RequirementCategory.WORK_AUTHORIZATION,
                    description=f"States {label}",
                )
            )

    @staticmethod
    def _classify_experience(
        requirements: JobRequirements, soft: list[ClassifiedRequirement]
    ) -> None:
        min_years = requirements.min_years_experience
        max_years = requirements.max_years_experience
        if min_years is None and max_years is None:
            return
        if min_years is not None and max_years is not None:
            description = f"{min_years}-{max_years} years of experience"
        elif min_years is not None:
            description = f"{min_years}+ years of experience"
        else:
            description = f"Up to {max_years} years of experience"
        soft.append(
            ClassifiedRequirement(
                category=RequirementCategory.EXPERIENCE, description=description
            )
        )

    @staticmethod
    def _classify_skills(
        requirements: JobRequirements, soft: list[ClassifiedRequirement]
    ) -> None:
        # Every skill is soft, "required" wording notwithstanding — a
        # skill gap is exactly the kind of wish-list item this classifier
        # exists to keep out of the hard set.
        for skill in requirements.required_skills:
            soft.append(
                ClassifiedRequirement(
                    category=RequirementCategory.SKILL, description=skill
                )
            )
        for skill in requirements.preferred_skills:
            soft.append(
                ClassifiedRequirement(
                    category=RequirementCategory.SKILL,
                    description=f"{skill} (preferred)",
                )
            )

    @staticmethod
    def _classify_preferences(
        requirements: JobRequirements, soft: list[ClassifiedRequirement]
    ) -> None:
        for preference in requirements.preferences:
            soft.append(
                ClassifiedRequirement(
                    category=RequirementCategory.PREFERENCE, description=preference
                )
            )
