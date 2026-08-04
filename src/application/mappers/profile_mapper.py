"""Mapper between the UserProfile entity and its output DTO.

Deliberately does **not** read `profile.eeo_self_identification`. That record has
its own mapper (`eeo_mapper.py`) and its own endpoint, and a static guard
(`test_the_eeo_record_is_unreachable_from_every_form_filling_module`) enforces the
short list of modules allowed to touch it. Folding it in here would put
demographic data into the payload every profile view loads.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import (
    AddressOutput,
    EducationOutput,
    ProfileLinksOutput,
    ProfileOutput,
    QualificationsOutput,
    SkillOutput,
    WorkHistoryOutput,
)
from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry


class ProfileMapper:
    """Translates domain entities into output DTOs."""

    @staticmethod
    def to_output(profile: UserProfile) -> ProfileOutput:
        return ProfileOutput(
            id=profile.id,
            user_id=profile.user_id,
            full_name=profile.full_name,
            email=str(profile.email),
            contact_source=profile.contact_source.value,
            phone=profile.phone,
            headline=profile.headline,
            location=profile.location,
            middle_name=profile.middle_name,
            preferred_name=profile.preferred_name,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            address=AddressOutput(
                street_address=profile.address.street_address,
                city=profile.address.city,
                state_or_region=profile.address.state_or_region,
                postal_code=profile.address.postal_code,
                country=profile.address.country,
                source=(
                    profile.address_source.value
                    if profile.address_source is not None
                    else None
                ),
            ),
            links=ProfileLinksOutput(
                portfolio_url=profile.links.portfolio_url,
                linkedin_url=profile.links.linkedin_url,
                github_url=profile.links.github_url,
                source=(
                    profile.links_source.value
                    if profile.links_source is not None
                    else None
                ),
            ),
            qualifications=QualificationsOutput(
                clearance_level=(
                    profile.clearance_level.value
                    if profile.clearance_level is not None
                    else None
                ),
                highest_degree=(
                    profile.highest_degree.value
                    if profile.highest_degree is not None
                    else None
                ),
            ),
            work_history=[
                ProfileMapper._work_history_to_output(entry)
                for entry in profile.work_history
            ],
            education=[
                ProfileMapper._education_to_output(entry) for entry in profile.education
            ],
            skills=[ProfileMapper._skill_to_output(skill) for skill in profile.skills],
        )

    @staticmethod
    def _work_history_to_output(entry: WorkHistoryEntry) -> WorkHistoryOutput:
        return WorkHistoryOutput(
            id=entry.id,
            company_name=entry.company_name,
            job_title=entry.job_title,
            start_date=entry.start_date,
            end_date=entry.end_date,
            location=entry.location,
            description=entry.description,
            source=entry.source.value,
        )

    @staticmethod
    def _education_to_output(entry: EducationEntry) -> EducationOutput:
        return EducationOutput(
            id=entry.id,
            institution_name=entry.institution_name,
            degree=entry.degree,
            majors=entry.majors,
            minors=entry.minors,
            field_of_study=entry.field_of_study,
            start_date=entry.start_date,
            end_date=entry.end_date,
            description=entry.description,
            source=entry.source.value,
        )

    @staticmethod
    def _skill_to_output(skill: Skill) -> SkillOutput:
        return SkillOutput(
            id=skill.id,
            name=skill.name,
            proficiency=(
                skill.proficiency.value if skill.proficiency is not None else None
            ),
            years_of_experience=skill.years_of_experience,
            source=skill.source.value,
        )
