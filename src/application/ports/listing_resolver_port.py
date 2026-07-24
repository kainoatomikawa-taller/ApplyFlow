"""ListingResolverPort — an outbound port for resolving a canonical apply
URL and description for a job listing whose aggregator source didn't
supply one or both (an empty `apply_url` or `description` on the raw
`AggregatorJobListing`).

Concrete implementations back this with a search API (Google Programmable
Search, Brave Search, ...) plus their own caching/quota policy — this
port's caller (`IngestAggregatorJobs`) never knows which provider answered
the call, only that a resolution was attempted and either produced fields
or came back empty. A cache hit, a quota-exhausted skip, a low-confidence
search, and "no resolver configured at all" all look identical from here:
`None`. Callers must treat `None` as "leave the listing as-is" (and skip
it if it's still missing required fields), never as an error to raise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedListingFields:
    """The fields a resolution fills in on an otherwise-incomplete listing."""

    apply_url: str
    description: str


class ListingResolverPort(ABC):
    """Abstraction over a search-API-backed listing resolver."""

    @abstractmethod
    async def resolve(
        self, *, company: str, title: str
    ) -> ResolvedListingFields | None:
        """Resolve a canonical apply URL/description for `company`.

        `title` scopes the search query for relevance only — caching is
        keyed on company alone (see `ResolvedListingRepository`), so a
        resolution found while handling one title is reused for every
        other listing from the same company, and the company is never
        searched again.
        """
