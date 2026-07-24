"""ResolvedListingRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. It is the permanent cache backing
`ListingResolverPort`: once a company has an entry here, it is never
searched again.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.resolved_listing import ResolvedListing


class ResolvedListingRepository(ABC):
    """Persistence contract for cached `ResolvedListing` records."""

    @abstractmethod
    async def get_by_normalized_company(
        self, normalized_company: str
    ) -> ResolvedListing | None:
        """Return the cached resolution for this company, or None if it has
        never been resolved before."""

    @abstractmethod
    async def save(self, resolved_listing: ResolvedListing) -> None:
        """Persist a newly resolved listing so it is never searched again."""
