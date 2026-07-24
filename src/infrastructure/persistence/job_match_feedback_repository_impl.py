"""SQLAlchemy implementation of the JobMatchFeedbackRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.repositories.job_match_feedback_repository import (
    JobMatchFeedbackRepository,
)
from src.domain.value_objects.feedback_rating import FeedbackRating
from src.infrastructure.persistence.models import JobMatchFeedbackModel


class SqlAlchemyJobMatchFeedbackRepository(JobMatchFeedbackRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, feedback: JobMatchFeedback) -> None:
        self._session.add(self._to_model(feedback))
        await self._session.commit()

    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedback]:
        result = await self._session.execute(
            select(JobMatchFeedbackModel)
            .where(JobMatchFeedbackModel.user_id == user_id)
            .order_by(JobMatchFeedbackModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_by_job_posting_id(
        self, job_posting_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedback]:
        result = await self._session.execute(
            select(JobMatchFeedbackModel)
            .where(JobMatchFeedbackModel.job_posting_id == job_posting_id)
            .order_by(JobMatchFeedbackModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_all(self, *, limit: int = 1000) -> list[JobMatchFeedback]:
        result = await self._session.execute(
            select(JobMatchFeedbackModel)
            .order_by(JobMatchFeedbackModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: JobMatchFeedback) -> JobMatchFeedbackModel:
        return JobMatchFeedbackModel(
            id=entity.id,
            user_id=entity.user_id,
            job_posting_id=entity.job_posting_id,
            rating=entity.rating.value,
            score_at_feedback=entity.score_at_feedback,
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_entity(model: JobMatchFeedbackModel) -> JobMatchFeedback:
        return JobMatchFeedback(
            id=model.id,
            user_id=model.user_id,
            job_posting_id=model.job_posting_id,
            rating=FeedbackRating(model.rating),
            score_at_feedback=model.score_at_feedback,
            created_at=model.created_at,
        )
