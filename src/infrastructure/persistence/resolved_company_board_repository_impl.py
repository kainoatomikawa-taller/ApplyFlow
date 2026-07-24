"""SQLAlchemy implementation of the ResolvedCompanyBoardRepository
interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.resolved_company_board import ResolvedCompanyBoard
from src.domain.repositories.resolved_company_board_repository import (
    ResolvedCompanyBoardRepository,
)
from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.persistence.models import ResolvedCompanyBoardModel


class SqlAlchemyResolvedCompanyBoardRepository(ResolvedCompanyBoardRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_normalized_company(
        self, normalized_company: str
    ) -> ResolvedCompanyBoard | None:
        model = await self._session.get(ResolvedCompanyBoardModel, normalized_company)
        return self._to_entity(model) if model else None

    async def save(self, board: ResolvedCompanyBoard) -> None:
        self._session.add(self._to_model(board))
        await self._session.commit()

    @staticmethod
    def _to_model(entity: ResolvedCompanyBoard) -> ResolvedCompanyBoardModel:
        return ResolvedCompanyBoardModel(
            normalized_company=entity.normalized_company,
            company=entity.company,
            provider=entity.provider.value,
            board_token=entity.board_token,
            resolved_at=entity.resolved_at,
        )

    @staticmethod
    def _to_entity(model: ResolvedCompanyBoardModel) -> ResolvedCompanyBoard:
        return ResolvedCompanyBoard(
            company=model.company,
            provider=AtsProvider(model.provider),
            board_token=model.board_token,
            resolved_at=model.resolved_at,
        )
