"""SQLAlchemy implementation of the JobPostingRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.job_posting import JobPosting
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.salary_range import SalaryPeriod, SalaryRange
from src.infrastructure.persistence.models import JobPostingModel


class SqlAlchemyJobPostingRepository(JobPostingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job_posting: JobPosting) -> None:
        self._session.add(self._to_model(job_posting))
        await self._session.commit()

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        model = await self._session.get(JobPostingModel, job_posting_id)
        return self._to_entity(model) if model else None

    async def find_duplicate(
        self,
        *,
        source: str,
        normalized_company: str,
        normalized_title: str,
        normalized_location: str | None,
    ) -> JobPosting | None:
        result = await self._session.execute(
            select(JobPostingModel)
            .where(
                JobPostingModel.source == source,
                JobPostingModel.normalized_company == normalized_company,
                JobPostingModel.normalized_title == normalized_title,
                JobPostingModel.normalized_location == normalized_location,
            )
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_entity(model) if model else None

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: JobPosting) -> JobPostingModel:
        return JobPostingModel(
            id=entity.id,
            source=entity.source,
            company=entity.company,
            title=entity.title,
            location=entity.location,
            is_remote=entity.is_remote,
            description=entity.description,
            apply_url=entity.apply_url,
            salary=SqlAlchemyJobPostingRepository._salary_to_dict(entity.salary),
            posted_at=entity.posted_at,
            normalized_company=entity.normalized_company,
            normalized_title=entity.normalized_title,
            normalized_location=entity.normalized_location,
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_entity(model: JobPostingModel) -> JobPosting:
        entity = JobPosting(
            id=model.id,
            source=model.source,
            company=model.company,
            title=model.title,
            apply_url=model.apply_url,
            description=model.description,
            is_remote=model.is_remote,
            location=model.location,
            salary=SqlAlchemyJobPostingRepository._salary_from_dict(model.salary),
            posted_at=model.posted_at,
            created_at=model.created_at,
        )
        return entity

    @staticmethod
    def _salary_to_dict(salary: SalaryRange | None) -> dict[str, object] | None:
        if salary is None:
            return None
        return {
            "currency": salary.currency,
            "period": salary.period.value,
            "min_amount": salary.min_amount,
            "max_amount": salary.max_amount,
        }

    @staticmethod
    def _salary_from_dict(data: dict[str, object] | None) -> SalaryRange | None:
        if data is None:
            return None
        min_amount = data["min_amount"]
        max_amount = data["max_amount"]
        assert isinstance(data["currency"], str)
        assert isinstance(data["period"], str)
        assert min_amount is None or isinstance(min_amount, int | float)
        assert max_amount is None or isinstance(max_amount, int | float)
        return SalaryRange(
            currency=data["currency"],
            period=SalaryPeriod(data["period"]),
            min_amount=min_amount,
            max_amount=max_amount,
        )
