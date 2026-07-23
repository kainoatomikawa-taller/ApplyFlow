"""SQLAlchemy implementation of the ProfileRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.infrastructure.persistence.models import (
    EducationModel,
    SkillModel,
    UserProfileModel,
    WorkHistoryModel,
)

_EAGER_LOAD_OPTIONS = (
    selectinload(UserProfileModel.work_history),
    selectinload(UserProfileModel.education),
    selectinload(UserProfileModel.skills),
)


class SqlAlchemyProfileRepository(ProfileRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, profile: UserProfile) -> None:
        self._session.add(self._to_model(profile))
        await self._session.commit()

    async def get_by_id(self, profile_id: str) -> UserProfile | None:
        result = await self._session.execute(
            select(UserProfileModel)
            .where(UserProfileModel.id == profile_id)
            .options(*_EAGER_LOAD_OPTIONS)
        )
        model = result.unique().scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        result = await self._session.execute(
            select(UserProfileModel)
            .where(UserProfileModel.user_id == user_id)
            .options(*_EAGER_LOAD_OPTIONS)
        )
        model = result.unique().scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def update(self, profile: UserProfile) -> None:
        result = await self._session.execute(
            select(UserProfileModel)
            .where(UserProfileModel.id == profile.id)
            .options(*_EAGER_LOAD_OPTIONS)
        )
        model = result.unique().scalar_one_or_none()
        if model is None:
            self._session.add(self._to_model(profile))
        else:
            self._apply_entity_to_model(profile, model)
        await self._session.commit()

    async def delete(self, profile_id: str) -> None:
        await self._session.execute(
            delete(UserProfileModel).where(UserProfileModel.id == profile_id)
        )
        await self._session.commit()

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: UserProfile) -> UserProfileModel:
        return UserProfileModel(
            id=entity.id,
            user_id=entity.user_id,
            full_name=entity.full_name,
            email=str(entity.email),
            phone=entity.phone,
            headline=entity.headline,
            location=entity.location,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            work_history=[
                SqlAlchemyProfileRepository._work_history_to_model(entry)
                for entry in entity.work_history
            ],
            education=[
                SqlAlchemyProfileRepository._education_to_model(entry)
                for entry in entity.education
            ],
            skills=[
                SqlAlchemyProfileRepository._skill_to_model(skill)
                for skill in entity.skills
            ],
        )

    @staticmethod
    def _work_history_to_model(entry: WorkHistoryEntry) -> WorkHistoryModel:
        return WorkHistoryModel(
            id=entry.id,
            company_name=entry.company_name,
            job_title=entry.job_title,
            location=entry.location,
            start_date=entry.start_date,
            end_date=entry.end_date,
            description=entry.description,
        )

    @staticmethod
    def _education_to_model(entry: EducationEntry) -> EducationModel:
        return EducationModel(
            id=entry.id,
            institution_name=entry.institution_name,
            degree=entry.degree,
            field_of_study=entry.field_of_study,
            start_date=entry.start_date,
            end_date=entry.end_date,
            description=entry.description,
        )

    @staticmethod
    def _skill_to_model(skill: Skill) -> SkillModel:
        return SkillModel(
            id=skill.id,
            name=skill.name,
            proficiency=(
                skill.proficiency.value if skill.proficiency is not None else None
            ),
            years_of_experience=skill.years_of_experience,
        )

    @staticmethod
    def _apply_entity_to_model(entity: UserProfile, model: UserProfileModel) -> None:
        model.full_name = entity.full_name
        model.email = str(entity.email)
        model.phone = entity.phone
        model.headline = entity.headline
        model.location = entity.location
        model.updated_at = entity.updated_at

        model.work_history = [
            SqlAlchemyProfileRepository._work_history_to_model(entry)
            for entry in entity.work_history
        ]
        model.education = [
            SqlAlchemyProfileRepository._education_to_model(entry)
            for entry in entity.education
        ]
        model.skills = [
            SqlAlchemyProfileRepository._skill_to_model(skill)
            for skill in entity.skills
        ]

    @staticmethod
    def _to_entity(model: UserProfileModel) -> UserProfile:
        return UserProfile(
            id=model.id,
            user_id=model.user_id,
            full_name=model.full_name,
            email=EmailAddress(model.email),
            phone=model.phone,
            headline=model.headline,
            location=model.location,
            work_history=[
                WorkHistoryEntry(
                    id=m.id,
                    company_name=m.company_name,
                    job_title=m.job_title,
                    start_date=m.start_date,
                    end_date=m.end_date,
                    location=m.location,
                    description=m.description,
                )
                for m in model.work_history
            ],
            education=[
                EducationEntry(
                    id=m.id,
                    institution_name=m.institution_name,
                    degree=m.degree,
                    field_of_study=m.field_of_study,
                    start_date=m.start_date,
                    end_date=m.end_date,
                    description=m.description,
                )
                for m in model.education
            ],
            skills=[
                Skill(
                    id=m.id,
                    name=m.name,
                    proficiency=(
                        ProficiencyLevel(m.proficiency)
                        if m.proficiency is not None
                        else None
                    ),
                    years_of_experience=m.years_of_experience,
                )
                for m in model.skills
            ],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
