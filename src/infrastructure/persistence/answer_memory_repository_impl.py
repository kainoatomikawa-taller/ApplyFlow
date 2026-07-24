"""SQLAlchemy implementation of the AnswerMemoryRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.answer_memory import AnswerMemory
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.infrastructure.persistence.models import AnswerMemoryModel


class SqlAlchemyAnswerMemoryRepository(AnswerMemoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, answer_memory: AnswerMemory) -> None:
        self._session.add(self._to_model(answer_memory))
        await self._session.commit()

    async def get_by_id(self, answer_memory_id: str) -> AnswerMemory | None:
        model = await self._session.get(AnswerMemoryModel, answer_memory_id)
        return self._to_entity(model) if model else None

    async def list_by_user_id(self, user_id: str) -> list[AnswerMemory]:
        result = await self._session.execute(
            select(AnswerMemoryModel)
            .where(AnswerMemoryModel.user_id == user_id)
            .order_by(AnswerMemoryModel.created_at.desc())
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def delete(self, answer_memory_id: str) -> None:
        await self._session.execute(
            delete(AnswerMemoryModel).where(AnswerMemoryModel.id == answer_memory_id)
        )
        await self._session.commit()

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: AnswerMemory) -> AnswerMemoryModel:
        return AnswerMemoryModel(
            id=entity.id,
            user_id=entity.user_id,
            question_text=entity.question_text,
            answer_text=entity.answer_text,
            embedding=entity.embedding,
            source=entity.source.value,
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_entity(model: AnswerMemoryModel) -> AnswerMemory:
        return AnswerMemory(
            id=model.id,
            user_id=model.user_id,
            question_text=model.question_text,
            answer_text=model.answer_text,
            embedding=list(model.embedding),
            source=ProvenanceSource(model.source),
            created_at=model.created_at,
        )
