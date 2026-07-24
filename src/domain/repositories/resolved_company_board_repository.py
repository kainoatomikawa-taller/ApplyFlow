"""ResolvedCompanyBoardRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. It is the permanent cache backing
`AtsListingResolver`: once a company has an entry here, its board is
never searched for again.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.resolved_company_board import ResolvedCompanyBoard


class ResolvedCompanyBoardRepository(ABC):
    """Persistence contract for cached `ResolvedCompanyBoard` records."""

    @abstractmethod
    async def get_by_normalized_company(
        self, normalized_company: str
    ) -> ResolvedCompanyBoard | None:
        """Return the cached board reference for this company, or None if
        it has never been resolved before."""

    @abstractmethod
    async def save(self, board: ResolvedCompanyBoard) -> None:
        """Persist a newly discovered board so it is never searched for
        again."""
