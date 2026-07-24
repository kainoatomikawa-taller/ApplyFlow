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
from src.domain.value_objects.address import Address
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.eeo_categories import (
    DisabilityStatus,
    GenderIdentity,
    RaceEthnicity,
    VeteranStatus,
)
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)
from src.infrastructure.persistence.models import (
    EducationModel,
    EeoSelfIdentificationModel,
    SkillModel,
    UserProfileModel,
    WorkAuthorizationModel,
    WorkHistoryModel,
)

_EAGER_LOAD_OPTIONS = (
    selectinload(UserProfileModel.work_history),
    selectinload(UserProfileModel.education),
    selectinload(UserProfileModel.skills),
    selectinload(UserProfileModel.work_authorization),
    selectinload(UserProfileModel.eeo_self_identification),
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
            contact_source=entity.contact_source.value,
            phone=entity.phone,
            headline=entity.headline,
            location=entity.location,
            street_address=entity.address.street_address,
            city=entity.address.city,
            state_or_region=entity.address.state_or_region,
            postal_code=entity.address.postal_code,
            country=entity.address.country,
            address_source=(
                entity.address_source.value
                if entity.address_source is not None
                else None
            ),
            portfolio_url=entity.links.portfolio_url,
            linkedin_url=entity.links.linkedin_url,
            github_url=entity.links.github_url,
            links_source=(
                entity.links_source.value if entity.links_source is not None else None
            ),
            clearance_level=(
                entity.clearance_level.value
                if entity.clearance_level is not None
                else None
            ),
            highest_degree=(
                entity.highest_degree.value
                if entity.highest_degree is not None
                else None
            ),
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
            work_authorization=(
                SqlAlchemyProfileRepository._work_authorization_to_model(
                    entity.work_authorization
                )
                if entity.work_authorization is not None
                else None
            ),
            eeo_self_identification=(
                SqlAlchemyProfileRepository._eeo_to_model(
                    entity.eeo_self_identification
                )
                if entity.eeo_self_identification is not None
                else None
            ),
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
            source=entry.source.value,
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
            source=entry.source.value,
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
            source=skill.source.value,
        )

    @staticmethod
    def _work_authorization_to_model(
        work_authorization: WorkAuthorization,
    ) -> WorkAuthorizationModel:
        return WorkAuthorizationModel(
            status=work_authorization.status.value,
            citizenship_country=work_authorization.citizenship_country,
            visa_type=work_authorization.visa_type,
            requires_sponsorship=work_authorization.requires_sponsorship,
            details=work_authorization.details,
            source=work_authorization.source.value,
        )

    @staticmethod
    def _eeo_to_model(eeo: EeoSelfIdentification) -> EeoSelfIdentificationModel:
        return EeoSelfIdentificationModel(
            gender_identity=(
                eeo.gender_identity.value if eeo.gender_identity is not None else None
            ),
            race_ethnicity=(
                eeo.race_ethnicity.value if eeo.race_ethnicity is not None else None
            ),
            veteran_status=(
                eeo.veteran_status.value if eeo.veteran_status is not None else None
            ),
            disability_status=(
                eeo.disability_status.value
                if eeo.disability_status is not None
                else None
            ),
            source=eeo.source.value,
        )

    @staticmethod
    def _apply_entity_to_model(entity: UserProfile, model: UserProfileModel) -> None:
        model.full_name = entity.full_name
        model.email = str(entity.email)
        model.contact_source = entity.contact_source.value
        model.phone = entity.phone
        model.headline = entity.headline
        model.location = entity.location
        model.street_address = entity.address.street_address
        model.city = entity.address.city
        model.state_or_region = entity.address.state_or_region
        model.postal_code = entity.address.postal_code
        model.country = entity.address.country
        model.address_source = (
            entity.address_source.value if entity.address_source is not None else None
        )
        model.portfolio_url = entity.links.portfolio_url
        model.linkedin_url = entity.links.linkedin_url
        model.github_url = entity.links.github_url
        model.links_source = (
            entity.links_source.value if entity.links_source is not None else None
        )
        model.clearance_level = (
            entity.clearance_level.value if entity.clearance_level is not None else None
        )
        model.highest_degree = (
            entity.highest_degree.value if entity.highest_degree is not None else None
        )
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
        model.work_authorization = (
            SqlAlchemyProfileRepository._work_authorization_to_model(
                entity.work_authorization
            )
            if entity.work_authorization is not None
            else None
        )
        model.eeo_self_identification = (
            SqlAlchemyProfileRepository._eeo_to_model(entity.eeo_self_identification)
            if entity.eeo_self_identification is not None
            else None
        )

    @staticmethod
    def _to_entity(model: UserProfileModel) -> UserProfile:
        return UserProfile(
            id=model.id,
            user_id=model.user_id,
            full_name=model.full_name,
            email=EmailAddress(model.email),
            contact_source=ProvenanceSource(model.contact_source),
            phone=model.phone,
            headline=model.headline,
            location=model.location,
            address=Address(
                street_address=model.street_address,
                city=model.city,
                state_or_region=model.state_or_region,
                postal_code=model.postal_code,
                country=model.country,
            ),
            address_source=(
                ProvenanceSource(model.address_source)
                if model.address_source is not None
                else None
            ),
            links=ProfileLinks(
                portfolio_url=model.portfolio_url,
                linkedin_url=model.linkedin_url,
                github_url=model.github_url,
            ),
            links_source=(
                ProvenanceSource(model.links_source)
                if model.links_source is not None
                else None
            ),
            clearance_level=(
                ClearanceLevel(model.clearance_level)
                if model.clearance_level is not None
                else None
            ),
            highest_degree=(
                DegreeLevel(model.highest_degree)
                if model.highest_degree is not None
                else None
            ),
            work_authorization=(
                SqlAlchemyProfileRepository._work_authorization_to_entity(
                    model.work_authorization
                )
                if model.work_authorization is not None
                else None
            ),
            eeo_self_identification=(
                SqlAlchemyProfileRepository._eeo_to_entity(
                    model.eeo_self_identification
                )
                if model.eeo_self_identification is not None
                else None
            ),
            work_history=[
                WorkHistoryEntry(
                    id=m.id,
                    company_name=m.company_name,
                    job_title=m.job_title,
                    start_date=m.start_date,
                    end_date=m.end_date,
                    location=m.location,
                    description=m.description,
                    source=ProvenanceSource(m.source),
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
                    source=ProvenanceSource(m.source),
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
                    source=ProvenanceSource(m.source),
                )
                for m in model.skills
            ],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _work_authorization_to_entity(
        model: WorkAuthorizationModel,
    ) -> WorkAuthorization:
        return WorkAuthorization(
            status=WorkAuthorizationStatus(model.status),
            citizenship_country=model.citizenship_country,
            visa_type=model.visa_type,
            requires_sponsorship=model.requires_sponsorship,
            details=model.details,
            source=ProvenanceSource(model.source),
        )

    @staticmethod
    def _eeo_to_entity(model: EeoSelfIdentificationModel) -> EeoSelfIdentification:
        return EeoSelfIdentification(
            source=ProvenanceSource(model.source),
            gender_identity=(
                GenderIdentity(model.gender_identity)
                if model.gender_identity is not None
                else None
            ),
            race_ethnicity=(
                RaceEthnicity(model.race_ethnicity)
                if model.race_ethnicity is not None
                else None
            ),
            veteran_status=(
                VeteranStatus(model.veteran_status)
                if model.veteran_status is not None
                else None
            ),
            disability_status=(
                DisabilityStatus(model.disability_status)
                if model.disability_status is not None
                else None
            ),
        )
