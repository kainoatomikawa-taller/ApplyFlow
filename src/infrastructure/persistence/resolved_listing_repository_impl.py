"""SQLAlchemy implementation of the ResolvedListingRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.resolved_listing import ResolvedListing
from src.domain.repositories.resolved_listing_repository import (
    ResolvedListingRepository,
)
from src.infrastructure.persistence.models import ResolvedListingModel


class SqlAlchemyResolvedListingRepository(ResolvedListingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_normalized_company(
        self, normalized_company: str
    ) -> ResolvedListing | None:
        model = await self._session.get(ResolvedListingModel, normalized_company)
        return self._to_entity(model) if model else None

    async def save(self, resolved_listing: ResolvedListing) -> None:
        self._session.add(self._to_model(resolved_listing))
        await self._session.commit()

    @staticmethod
    def _to_model(entity: ResolvedListing) -> ResolvedListingModel:
        return ResolvedListingModel(
            normalized_company=entity.normalized_company,
            company=entity.company,
            apply_url=entity.apply_url,
            description=entity.description,
            resolved_at=entity.resolved_at,
        )

    @staticmethod
    def _to_entity(model: ResolvedListingModel) -> ResolvedListing:
        return ResolvedListing(
            company=model.company,
            apply_url=model.apply_url,
            description=model.description,
            resolved_at=model.resolved_at,
        )
