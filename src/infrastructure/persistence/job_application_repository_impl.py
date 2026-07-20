"""SQLAlchemy implementation of the JobApplicationRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.job_application import JobApplication
from src.domain.repositories.job_application_repository import (
    JobApplicationRepository,
)
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.match_score import MatchScore
from src.infrastructure.persistence.models import JobApplicationModel


class SqlAlchemyJobApplicationRepository(JobApplicationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, application: JobApplication) -> None:
        self._session.add(self._to_model(application))
        await self._session.commit()

    async def get_by_id(self, application_id: str) -> JobApplication | None:
        result = await self._session.execute(
            select(JobApplicationModel).where(JobApplicationModel.id == application_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def update(self, application: JobApplication) -> None:
        model = await self._session.get(JobApplicationModel, application.id)
        if model is None:
            self._session.add(self._to_model(application))
        else:
            self._apply_entity_to_model(application, model)
        await self._session.commit()

    async def list_by_candidate(self, candidate_email: str) -> list[JobApplication]:
        result = await self._session.execute(
            select(JobApplicationModel).where(
                JobApplicationModel.candidate_email == candidate_email.lower()
            )
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def delete(self, application_id: str) -> None:
        await self._session.execute(
            delete(JobApplicationModel).where(JobApplicationModel.id == application_id)
        )
        await self._session.commit()

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: JobApplication) -> JobApplicationModel:
        return JobApplicationModel(
            id=entity.id,
            candidate_email=str(entity.candidate_email),
            company_name=entity.company_name,
            role_title=entity.role_title,
            job_description=entity.job_description,
            status=entity.status.value,
            match_score=(
                int(entity.match_score) if entity.match_score is not None else None
            ),
            tailored_cover_letter=entity.tailored_cover_letter,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _apply_entity_to_model(
        entity: JobApplication, model: JobApplicationModel
    ) -> None:
        model.candidate_email = str(entity.candidate_email)
        model.company_name = entity.company_name
        model.role_title = entity.role_title
        model.job_description = entity.job_description
        model.status = entity.status.value
        model.match_score = (
            int(entity.match_score) if entity.match_score is not None else None
        )
        model.tailored_cover_letter = entity.tailored_cover_letter
        model.updated_at = entity.updated_at

    @staticmethod
    def _to_entity(model: JobApplicationModel) -> JobApplication:
        return JobApplication(
            id=model.id,
            candidate_email=EmailAddress(model.candidate_email),
            company_name=model.company_name,
            role_title=model.role_title,
            job_description=model.job_description,
            status=ApplicationStatus(model.status),
            match_score=(
                MatchScore(model.match_score) if model.match_score is not None else None
            ),
            tailored_cover_letter=model.tailored_cover_letter,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
