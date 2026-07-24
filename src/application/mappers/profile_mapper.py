"""Mapper between the UserProfile entity and its output DTO."""

from __future__ import annotations

from src.application.dtos.profile_dtos import (
    EducationOutput,
    ProfileOutput,
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
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            work_history=[
                ProfileMapper._work_history_to_output(entry)
                for entry in profile.work_history
            ],
            education=[
                ProfileMapper._education_to_output(entry)
                for entry in profile.education
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
