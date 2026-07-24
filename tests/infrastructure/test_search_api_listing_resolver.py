"""Tests for SearchApiListingResolver — the ListingResolverPort
implementation orchestrating the cache, quota, and raw search client.

`ResolvedListingRepository`, `DailySearchQuota`, and `BraveSearchClient`
are all replaced with in-memory fakes, so these run offline and prove:
cache-first lookup, quota enforcement, save-after-resolve, and graceful
degradation on quota exhaustion or a search-client error.
"""

from __future__ import annotations

import pytest

from src.application.exceptions import ExternalServiceError
from src.domain.entities.resolved_listing import ResolvedListing
from src.domain.repositories.resolved_listing_repository import (
    ResolvedListingRepository,
)
from src.domain.services.text_normalization import normalize_text
from src.infrastructure.search.brave_search_client import BraveSearchResult
from src.infrastructure.search.search_api_listing_resolver import (
    SearchApiListingResolver,
)


class FakeResolvedListingRepository(ResolvedListingRepository):
    def __init__(self) -> None:
        self.saved: list[ResolvedListing] = []

    async def get_by_normalized_company(
        self, normalized_company: str
    ) -> ResolvedListing | None:
        return next(
            (r for r in self.saved if r.normalized_company == normalized_company),
            None,
        )

    async def save(self, resolved_listing: ResolvedListing) -> None:
        self.saved.append(resolved_listing)


class FakeQuota:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.consume_calls = 0

    async def try_consume(self) -> bool:
        self.consume_calls += 1
        return self.allowed


class FakeSearchClient:
    def __init__(
        self, result: BraveSearchResult | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error
        self.queries: list[str] = []

    async def search(self, query: str) -> BraveSearchResult | None:
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return self._result


@pytest.mark.asyncio
async def test_cache_hit_never_touches_quota_or_search_client():
    cache = FakeResolvedListingRepository()
    cache.saved.append(
        ResolvedListing(
            company="Acme Corp",
            apply_url="https://acme.example.com/careers",
            description="Acme's careers page.",
        )
    )
    quota = FakeQuota()
    search_client = FakeSearchClient()
    resolver = SearchApiListingResolver(cache, quota, search_client)

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is not None
    assert result.apply_url == "https://acme.example.com/careers"
    assert quota.consume_calls == 0
    assert search_client.queries == []


@pytest.mark.asyncio
async def test_cache_miss_consumes_quota_and_calls_search_client():
    cache = FakeResolvedListingRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(
        result=BraveSearchResult(
            url="https://acme.example.com/careers", description="Acme's page."
        )
    )
    resolver = SearchApiListingResolver(cache, quota, search_client)

    result = await resolver.resolve(company="Acme Corp", title="Backend Engineer")

    assert result is not None
    assert result.apply_url == "https://acme.example.com/careers"
    assert result.description == "Acme's page."
    assert quota.consume_calls == 1
    assert search_client.queries == ["Acme Corp Backend Engineer apply"]


@pytest.mark.asyncio
async def test_successful_resolution_is_saved_to_the_cache():
    cache = FakeResolvedListingRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(
        result=BraveSearchResult(
            url="https://acme.example.com/careers", description="Acme's page."
        )
    )
    resolver = SearchApiListingResolver(cache, quota, search_client)

    await resolver.resolve(company="Acme Corp", title="Engineer")

    assert len(cache.saved) == 1
    assert cache.saved[0].normalized_company == normalize_text("Acme Corp")


@pytest.mark.asyncio
async def test_quota_exhaustion_degrades_to_none_without_calling_search():
    cache = FakeResolvedListingRepository()
    quota = FakeQuota(allowed=False)
    search_client = FakeSearchClient()
    resolver = SearchApiListingResolver(cache, quota, search_client)

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None
    assert search_client.queries == []


@pytest.mark.asyncio
async def test_no_search_result_returns_none_and_saves_nothing():
    cache = FakeResolvedListingRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(result=None)
    resolver = SearchApiListingResolver(cache, quota, search_client)

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None
    assert cache.saved == []


@pytest.mark.asyncio
async def test_search_client_error_degrades_to_none_instead_of_raising():
    cache = FakeResolvedListingRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(error=ExternalServiceError("boom"))
    resolver = SearchApiListingResolver(cache, quota, search_client)

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None
