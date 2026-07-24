"""SoftPreferenceEvaluator — a pure domain service that decides which of a
job's soft preferences (see `RequirementClassifier`) a candidate's
`UserProfile` actually meets, and which are genuine gaps.

Mirrors `HardDisqualifierFilter`'s structure exactly, but for the soft
set: it only evaluates categories `RequirementClassifier` has already put
in `soft` (never re-deriving what counts as soft), and it never claims a
preference is met or unmet when the profile simply doesn't say — silence
on unknown data is what keeps the resulting "why this fits"/"what's
missing" summary honest rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.domain.entities.user_profile import UserProfile
from src.domain.services.requirement_classifier import (
    ClassifiedRequirement,
    RequirementClassifier,
)
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.requirement_category import RequirementCategory

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


def _total_experience_years(profile: UserProfile, *, as_of: date) -> int | None:
    """A simple, approximate total: the sum of each work-history entry's
    span (open-ended entries run through `as_of`). Overlapping roles are
    each counted in full rather than deduplicated — a deliberate
    simplification, since this only ever backs an approximate "meets a
    stated experience floor" check, not a precise tenure calculation.

    Returns None when the profile has no work history at all, so an
    empty history is treated as unknown rather than zero years.
    """
    if not profile.work_history:
        return None
    total_days = sum(
        ((entry.end_date or as_of) - entry.start_date).days
        for entry in profile.work_history
    )
    return total_days // 365


@dataclass(frozen=True)
class SoftPreferenceEvaluation:
    """Which of a job's soft preferences the candidate meets, and which
    are genuine gaps. Preferences the profile has no data to judge either
    way appear in neither tuple."""

    met: tuple[ClassifiedRequirement, ...] = ()
    gaps: tuple[ClassifiedRequirement, ...] = ()

    @property
    def fit_score(self) -> int:
        """A 0-100 fit score: the share of judged soft preferences the
        candidate meets. A posting with no judged preferences at all
        (nothing stated, or nothing the profile has data to confirm
        either way) scores 100 — silence is never held against a
        candidate, mirroring this service's own "unknown is not a gap"
        rule. Ranking gets a deterministic, profile-grounded number this
        way without asking the LLM (which only ever writes the narrative
        rationale) to judge fit."""
        total = len(self.met) + len(self.gaps)
        if total == 0:
            return 100
        return round(100 * len(self.met) / total)


class SoftPreferenceEvaluator:
    """Checks a `UserProfile` against a job's soft `JobRequirements`,
    evaluating only the categories `RequirementClassifier` has already
    classified as soft."""

    def __init__(self, classifier: RequirementClassifier | None = None) -> None:
        self._classifier = classifier or RequirementClassifier()

    def evaluate(
        self, profile: UserProfile, requirements: JobRequirements, *, as_of: date
    ) -> SoftPreferenceEvaluation:
        soft_categories = {
            item.category for item in self._classifier.classify(requirements).soft
        }
        met: list[ClassifiedRequirement] = []
        gaps: list[ClassifiedRequirement] = []

        if RequirementCategory.DEGREE in soft_categories:
            self._evaluate_degree(profile, requirements, met, gaps)
        if RequirementCategory.CLEARANCE in soft_categories:
            self._evaluate_clearance(profile, requirements, met, gaps)
        if RequirementCategory.SKILL in soft_categories:
            self._evaluate_skills(profile, requirements, met, gaps)
        if RequirementCategory.EXPERIENCE in soft_categories:
            self._evaluate_experience(profile, requirements, met, gaps, as_of=as_of)

        return SoftPreferenceEvaluation(met=tuple(met), gaps=tuple(gaps))

    @staticmethod
    def _evaluate_degree(
        profile: UserProfile,
        requirements: JobRequirements,
        met: list[ClassifiedRequirement],
        gaps: list[ClassifiedRequirement],
    ) -> None:
        required_level = requirements.degree_level
        candidate_level = profile.highest_degree
        if required_level is None or candidate_level is None:
            return
        item = ClassifiedRequirement(
            category=RequirementCategory.DEGREE,
            description=f"{_DEGREE_LABELS[required_level]} preferred",
        )
        meets_bar = _DEGREE_RANK[candidate_level] >= _DEGREE_RANK[required_level]
        (met if meets_bar else gaps).append(item)

    @staticmethod
    def _evaluate_clearance(
        profile: UserProfile,
        requirements: JobRequirements,
        met: list[ClassifiedRequirement],
        gaps: list[ClassifiedRequirement],
    ) -> None:
        required_level = requirements.clearance_level
        candidate_level = profile.clearance_level
        if required_level is None or candidate_level is None:
            return
        item = ClassifiedRequirement(
            category=RequirementCategory.CLEARANCE,
            description=f"{_CLEARANCE_LABELS[required_level]} preferred",
        )
        target = (
            met
            if _CLEARANCE_RANK[candidate_level] >= _CLEARANCE_RANK[required_level]
            else gaps
        )
        target.append(item)

    @staticmethod
    def _evaluate_skills(
        profile: UserProfile,
        requirements: JobRequirements,
        met: list[ClassifiedRequirement],
        gaps: list[ClassifiedRequirement],
    ) -> None:
        candidate_skills = {skill.name.strip().lower() for skill in profile.skills}

        for skill in requirements.required_skills:
            item = ClassifiedRequirement(
                category=RequirementCategory.SKILL, description=skill
            )
            (met if skill.strip().lower() in candidate_skills else gaps).append(item)

        for skill in requirements.preferred_skills:
            item = ClassifiedRequirement(
                category=RequirementCategory.SKILL,
                description=f"{skill} (preferred)",
            )
            (met if skill.strip().lower() in candidate_skills else gaps).append(item)

    @staticmethod
    def _evaluate_experience(
        profile: UserProfile,
        requirements: JobRequirements,
        met: list[ClassifiedRequirement],
        gaps: list[ClassifiedRequirement],
        *,
        as_of: date,
    ) -> None:
        min_years = requirements.min_years_experience
        if min_years is None:
            return
        candidate_years = _total_experience_years(profile, as_of=as_of)
        if candidate_years is None:
            return
        item = ClassifiedRequirement(
            category=RequirementCategory.EXPERIENCE,
            description=f"{min_years}+ years of experience",
        )
        (met if candidate_years >= min_years else gaps).append(item)
