"""SQLAlchemy implementation of the JobPostingRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.job_posting import JobPosting
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.job_posting_status import JobPostingStatus
from src.domain.value_objects.salary_range import SalaryPeriod, SalaryRange
from src.infrastructure.persistence.models import JobPostingModel


class SqlAlchemyJobPostingRepository(JobPostingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job_posting: JobPosting) -> None:
        self._session.add(self._to_model(job_posting))
        await self._session.commit()

    async def update(self, job_posting: JobPosting) -> None:
        await self._session.merge(self._to_model(job_posting))
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

    async def list_due_for_staleness_check(
        self, *, as_of: datetime, recheck_after_days: int, batch_size: int
    ) -> list[JobPosting]:
        cutoff = as_of - timedelta(days=recheck_after_days)
        result = await self._session.execute(
            select(JobPostingModel)
            .where(
                JobPostingModel.status == JobPostingStatus.ACTIVE.value,
                or_(
                    JobPostingModel.last_checked_at.is_(None),
                    JobPostingModel.last_checked_at <= cutoff,
                ),
            )
            .order_by(JobPostingModel.last_checked_at.asc().nulls_first())
            .limit(batch_size)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        result = await self._session.execute(
            select(JobPostingModel)
            .where(JobPostingModel.status == JobPostingStatus.ACTIVE.value)
            .order_by(JobPostingModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

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
            status=entity.status.value,
            last_checked_at=entity.last_checked_at,
            consecutive_link_failures=entity.consecutive_link_failures,
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
            status=JobPostingStatus(model.status),
            last_checked_at=model.last_checked_at,
            consecutive_link_failures=model.consecutive_link_failures,
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
