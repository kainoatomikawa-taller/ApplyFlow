"""ListingResolverPort — an outbound port for resolving a canonical apply
URL and description for a job listing whose aggregator source didn't
supply one or both (an empty `apply_url` or `description` on the raw
`AggregatorJobListing`).

Concrete implementations resolve against the company's own ATS board
(Greenhouse/Lever/Ashby — see `AtsListingResolver`), using a search API
only to locate that board when it isn't already cached, plus their own
caching/quota policy — this port's caller (`IngestAggregatorJobs`) never
knows which provider answered the call, only that a resolution was
attempted and either produced fields or came back empty. A cache hit, a
quota-exhausted skip, a board with no matching title, and "no resolver
configured at all" all look identical from here: `None`. Callers must
treat `None` as "leave the listing as-is" (and skip it if it's still
missing required fields), never as an error to raise.
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

        `title` scopes the lookup to a specific job. WHICH board a
        company posts through is what's cached and keyed on company alone
        (see `ResolvedCompanyBoardRepository`) — that company is never
        searched for again — but the fields returned here are still
        looked up fresh per title, so two different open roles at the
        same company each get their own correct apply URL/description.
        """
