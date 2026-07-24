"""CandidateFactExtractor — a pure domain service that turns a
`UserProfile` into a flat list of plain-language fact strings.

This is the profile-side half of the fact base `DetectJobRequirementGaps`
checks a job's requirements against (the other half is a candidate's
`AnswerMemory` records, which are already free text and need no
extraction). Only fields the profile actually states become a fact — an
unset `highest_degree`/`clearance_level`/`work_authorization` or an empty
`skills`/`work_history` list simply contributes nothing, never a guessed
placeholder. That keeps every fact handed to the LLM-driven gap detector
traceable to something the candidate's data actually says, per the
"never fabricate a fact" contract `ProvenanceSource` documents for
downstream generation.
"""

from __future__ import annotations

from datetime import date

from src.domain.entities.user_profile import UserProfile
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
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
    WorkAuthorizationStatus.CITIZEN: "U.S. citizen",
    WorkAuthorizationStatus.PERMANENT_RESIDENT: "Permanent resident",
    WorkAuthorizationStatus.VISA_HOLDER: "Holds an existing work visa",
    WorkAuthorizationStatus.REQUIRES_SPONSORSHIP: "Requires visa sponsorship",
    WorkAuthorizationStatus.NOT_AUTHORIZED: "Not authorized to work",
    WorkAuthorizationStatus.OTHER: "Other work authorization status",
}


def _total_experience_years(profile: UserProfile, *, as_of: date) -> int | None:
    """Mirrors `SoftPreferenceEvaluator`'s own approximate total: the sum
    of each work-history entry's span, overlaps counted in full. See that
    service's module docstring for why this simplification is acceptable
    here too — it only ever backs a plain "N years of experience" fact,
    not a precise tenure calculation."""
    if not profile.work_history:
        return None
    total_days = sum(
        ((entry.end_date or as_of) - entry.start_date).days
        for entry in profile.work_history
    )
    return total_days // 365


class CandidateFactExtractor:
    """Extracts every stated fact on a `UserProfile` as a plain-language
    string, suitable for handing to an LLM as ground truth about a
    candidate."""

    def extract(self, profile: UserProfile, *, as_of: date) -> tuple[str, ...]:
        facts: list[str] = []

        if profile.highest_degree is not None:
            degree_label = _DEGREE_LABELS[profile.highest_degree]
            facts.append(f"Highest completed degree: {degree_label}")

        if profile.clearance_level is not None:
            facts.append(f"Holds a {_CLEARANCE_LABELS[profile.clearance_level]}")

        if profile.work_authorization is not None:
            facts.append(
                "Work authorization: "
                f"{_WORK_AUTHORIZATION_LABELS[profile.work_authorization.status]}"
            )

        total_years = _total_experience_years(profile, as_of=as_of)
        if total_years is not None:
            facts.append(f"Has {total_years} years of professional work experience")

        for entry in profile.work_history:
            end = "present" if entry.end_date is None else entry.end_date.isoformat()
            span = f"{entry.start_date.isoformat()} to {end}"
            facts.append(
                f"Worked as {entry.job_title} at {entry.company_name} ({span})"
            )

        for skill in profile.skills:
            detail = skill.name
            if skill.years_of_experience is not None:
                detail += f" ({skill.years_of_experience} years)"
            facts.append(f"Skill: {detail}")

        if profile.address.country:
            facts.append(f"Located in {profile.address.country}")

        return tuple(facts)
