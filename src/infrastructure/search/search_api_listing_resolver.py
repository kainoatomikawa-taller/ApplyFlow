"""SearchApiListingResolver — the ListingResolverPort implementation
backing `IngestAggregatorJobs` with Brave's Web Search API.

Ties together three concerns, each owned by its own collaborator so this
class stays pure orchestration:
  - `ResolvedListingRepository` — a permanent cache. This is the single
    most important piece for a ~100-query/day free tier: once a company
    has been resolved, it is checked first and *never* searched again,
    regardless of how many more of that company's listings arrive without
    a URL/description.
  - `DailySearchQuota` — a Redis-backed counter so the daily allowance is
    respected across every worker process, degrading to `None` (not an
    error) once exhausted.
  - `BraveSearchClient` — the raw HTTP call to Brave's JSON API.

Any failure from the search client itself (rate limited past its own
retries, a transient network error) is also treated as a graceful
degradation — one company's search failure must never abort the rest of
an ingestion run.
"""

from __future__ import annotations

import logging

from src.application.exceptions import ExternalServiceError
from src.application.ports.listing_resolver_port import (
    ListingResolverPort,
    ResolvedListingFields,
)
from src.domain.entities.resolved_listing import ResolvedListing
from src.domain.repositories.resolved_listing_repository import (
    ResolvedListingRepository,
)
from src.domain.services.text_normalization import normalize_text
from src.infrastructure.search.brave_search_client import BraveSearchClient
from src.infrastructure.search.daily_search_quota import DailySearchQuota

logger = logging.getLogger(__name__)


class SearchApiListingResolver(ListingResolverPort):
    def __init__(
        self,
        cache: ResolvedListingRepository,
        quota: DailySearchQuota,
        search_client: BraveSearchClient,
    ) -> None:
        self._cache = cache
        self._quota = quota
        self._search_client = search_client

    async def resolve(
        self, *, company: str, title: str
    ) -> ResolvedListingFields | None:
        normalized_company = normalize_text(company)

        cached = await self._cache.get_by_normalized_company(normalized_company)
        if cached is not None:
            return ResolvedListingFields(
                apply_url=cached.apply_url, description=cached.description
            )

        if not await self._quota.try_consume():
            logger.warning(
                "search API daily quota exhausted; skipping resolution for "
                "company=%r",
                company,
            )
            return None

        try:
            result = await self._search_client.search(f"{company} {title} apply")
        except ExternalServiceError as exc:
            logger.warning(
                "search API request failed for company=%r: %s", company, exc
            )
            return None

        if result is None:
            return None

        resolved = ResolvedListing(
            company=company, apply_url=result.url, description=result.description
        )
        await self._cache.save(resolved)
        return ResolvedListingFields(
            apply_url=resolved.apply_url, description=resolved.description
        )
