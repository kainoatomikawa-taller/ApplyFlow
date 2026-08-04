"""CandidateFactExtractor — a pure domain service that turns a
`UserProfile` into plain-language fact statements.

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

Two views of that same profile data
-----------------------------------
`extract` answers "what is true about this candidate", as plain strings,
for judging fit. `extract_provenance_backed` answers "what may we
*assert* about this candidate, and on whose authority", as
`ProvenanceBackedFact`s, for `ProvenanceGuard` to validate generated
output against. They differ in two deliberate ways:

- The provenance-backed view includes contact details, address, links,
  and education, because a tailored resume has to be able to state them
  and the guard would otherwise strip its own header. Fit judging doesn't
  need them, so `extract` leaves them out as noise.
- It excludes what carries no provenance to cite. `highest_degree` and
  `clearance_level` are scalar fields with no `*_source` tag of their own
  in the data model (unlike `work_authorization`, education, and skills),
  so nothing can honestly vouch for them — a resume's degree claim has to
  come from a real `EducationEntry` instead. It also excludes the derived
  "N years of professional work experience" total: it is computed here,
  not stated by any resume, form, or answer, so tagging it with one of
  the three sources would be a small fabrication of exactly the kind this
  module exists to prevent.
"""

from __future__ import annotations

from datetime import date

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.provenance_backed_fact import ProvenanceBackedFact
from src.domain.value_objects.provenance_source import ProvenanceSource
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


def _work_history_text(entry: WorkHistoryEntry) -> str:
    end = "present" if entry.end_date is None else entry.end_date.isoformat()
    span = f"{entry.start_date.isoformat()} to {end}"
    return f"Worked as {entry.job_title} at {entry.company_name} ({span})"


def _skill_text(skill: Skill) -> str:
    detail = skill.name
    if skill.years_of_experience is not None:
        detail += f" ({skill.years_of_experience} years)"
    return f"Skill: {detail}"


def _education_text(entry: EducationEntry) -> str:
    text = f"Studied {entry.degree}"
    if entry.majors:
        text += f" with a major in {' and '.join(entry.majors)}"
    if entry.minors:
        # Stated as a minor explicitly. This text is the ground truth a tailored
        # resume is checked against, so a minor recorded here as though it were a
        # major would license the model to claim the stronger credential.
        text += f" and a minor in {' and '.join(entry.minors)}"
    text += f" at {entry.institution_name}"
    if entry.end_date is not None:
        text += f" (completed {entry.end_date.isoformat()})"
    return text


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

        facts.extend(_work_history_text(entry) for entry in profile.work_history)
        facts.extend(_skill_text(skill) for skill in profile.skills)

        if profile.address.country:
            facts.append(f"Located in {profile.address.country}")

        return tuple(facts)

    def extract_provenance_backed(
        self, profile: UserProfile
    ) -> tuple[ProvenanceBackedFact, ...]:
        """Every fact on `profile` that carries a `ProvenanceSource`,
        tagged with it — the ground truth `ProvenanceGuard` checks
        generated output against.

        Each fact is attributed to the source the data model actually
        records for it: the contact bundle's `contact_source`, the
        address/links groups' own tags, and the per-row `source` on work
        history, education, skills, and work authorization. Nothing is
        attributed by assumption, and anything the model can't attribute
        is left out entirely (see the module docstring).

        No `as_of` parameter, deliberately: a provenance-backed fact is
        something the candidate stated, so none of it depends on today's
        date.
        """
        facts: list[ProvenanceBackedFact] = []

        def add(text: str, source: ProvenanceSource) -> None:
            facts.append(ProvenanceBackedFact(text=text, source=source))

        contact = profile.contact_source
        add(f"Name: {profile.full_name}", contact)
        add(f"Email: {profile.email}", contact)
        if profile.phone:
            add(f"Phone: {profile.phone}", contact)
        if profile.headline:
            add(f"Headline: {profile.headline}", contact)
        if profile.location:
            add(f"Location: {profile.location}", contact)

        if profile.address_source is not None:
            address_parts = [
                part
                for part in (
                    profile.address.street_address,
                    profile.address.city,
                    profile.address.state_or_region,
                    profile.address.postal_code,
                    profile.address.country,
                )
                if part
            ]
            if address_parts:
                add(f"Address: {', '.join(address_parts)}", profile.address_source)

        if profile.links_source is not None:
            for label, url in (
                ("Portfolio", profile.links.portfolio_url),
                ("LinkedIn", profile.links.linkedin_url),
                ("GitHub", profile.links.github_url),
            ):
                if url:
                    add(f"{label}: {url}", profile.links_source)

        if profile.work_authorization is not None:
            status_label = _WORK_AUTHORIZATION_LABELS[profile.work_authorization.status]
            add(
                f"Work authorization: {status_label}",
                profile.work_authorization.source,
            )

        for entry in profile.work_history:
            add(_work_history_text(entry), entry.source)
            if entry.location:
                add(
                    f"{entry.job_title} at {entry.company_name} "
                    f"was based in {entry.location}",
                    entry.source,
                )
            if entry.description:
                add(
                    f"{entry.job_title} at {entry.company_name}: {entry.description}",
                    entry.source,
                )

        for education in profile.education:
            add(_education_text(education), education.source)
            if education.description:
                add(
                    f"{education.degree} at {education.institution_name}: "
                    f"{education.description}",
                    education.source,
                )

        for skill in profile.skills:
            add(_skill_text(skill), skill.source)

        return tuple(facts)
