"""SQLAlchemy implementation of the ResumeRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.resume import Resume
from src.domain.repositories.resume_repository import ResumeRepository
from src.infrastructure.persistence.models import ResumeModel


class SqlAlchemyResumeRepository(ResumeRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, resume: Resume) -> None:
        self._session.add(self._to_model(resume))
        await self._session.commit()

    async def get_by_id(self, resume_id: str) -> Resume | None:
        model = await self._session.get(ResumeModel, resume_id)
        return self._to_entity(model) if model else None

    async def list_by_user_id(self, user_id: str) -> list[Resume]:
        result = await self._session.execute(
            select(ResumeModel)
            .where(ResumeModel.user_id == user_id)
            .order_by(ResumeModel.created_at.desc())
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def delete(self, resume_id: str) -> None:
        await self._session.execute(
            delete(ResumeModel).where(ResumeModel.id == resume_id)
        )
        await self._session.commit()

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: Resume) -> ResumeModel:
        return ResumeModel(
            id=entity.id,
            user_id=entity.user_id,
            original_filename=entity.original_filename,
            content_type=entity.content_type,
            size_bytes=entity.size_bytes,
            storage_key=entity.storage_key,
            extracted_text=entity.extracted_text,
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_entity(model: ResumeModel) -> Resume:
        return Resume(
            id=model.id,
            user_id=model.user_id,
            original_filename=model.original_filename,
            content_type=model.content_type,
            size_bytes=model.size_bytes,
            storage_key=model.storage_key,
            extracted_text=model.extracted_text,
            created_at=model.created_at,
        )
