"""Tests for AtsListingResolver — the ListingResolverPort implementation
orchestrating the board cache, quota, search client, and per-provider ATS
board clients.

`ResolvedCompanyBoardRepository`, `DailySearchQuota`, `BraveSearchClient`,
and `AtsBoardClientPort` are all replaced with in-memory fakes, so these
run offline and prove: cache-first board lookup, quota enforcement,
board-discovery via a domain-restricted search, per-listing (uncached)
job lookup against the discovered board, and graceful degradation on
quota exhaustion, no board found, or a search/board-client error.
"""

from __future__ import annotations

import pytest

from src.application.exceptions import ExternalServiceError
from src.application.ports.listing_resolver_port import ResolvedListingFields
from src.domain.entities.resolved_company_board import ResolvedCompanyBoard
from src.domain.repositories.resolved_company_board_repository import (
    ResolvedCompanyBoardRepository,
)
from src.domain.services.text_normalization import normalize_text
from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.search.ats_listing_resolver import AtsListingResolver
from src.infrastructure.search.brave_search_client import BraveSearchResult


class FakeBoardRepository(ResolvedCompanyBoardRepository):
    def __init__(self) -> None:
        self.saved: list[ResolvedCompanyBoard] = []

    async def get_by_normalized_company(
        self, normalized_company: str
    ) -> ResolvedCompanyBoard | None:
        return next(
            (r for r in self.saved if r.normalized_company == normalized_company),
            None,
        )

    async def save(self, board: ResolvedCompanyBoard) -> None:
        self.saved.append(board)


class FakeQuota:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.consume_calls = 0

    async def try_consume(self) -> bool:
        self.consume_calls += 1
        return self.allowed


class FakeSearchClient:
    def __init__(
        self,
        results: list[BraveSearchResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._results = results or []
        self._error = error
        self.queries: list[str] = []

    async def search_many(
        self, query: str, count: int = 5
    ) -> list[BraveSearchResult]:
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return self._results


class FakeAtsBoardClient:
    def __init__(
        self,
        provider: AtsProvider,
        result: ResolvedListingFields | None = None,
        error: Exception | None = None,
    ) -> None:
        self._provider = provider
        self._result = result
        self._error = error
        self.calls: list[tuple[str, str]] = []

    @property
    def provider(self) -> AtsProvider:
        return self._provider

    async def find_job(
        self, *, board_token: str, title: str
    ) -> ResolvedListingFields | None:
        self.calls.append((board_token, title))
        if self._error is not None:
            raise self._error
        return self._result


@pytest.mark.asyncio
async def test_cached_board_never_touches_quota_or_search_client():
    board_cache = FakeBoardRepository()
    board_cache.saved.append(
        ResolvedCompanyBoard(
            company="Acme Corp", provider=AtsProvider.GREENHOUSE, board_token="acme"
        )
    )
    quota = FakeQuota()
    search_client = FakeSearchClient()
    greenhouse = FakeAtsBoardClient(
        AtsProvider.GREENHOUSE,
        result=ResolvedListingFields(
            apply_url="https://boards.greenhouse.io/acme/jobs/1",
            description="Full job description.",
        ),
    )
    resolver = AtsListingResolver(
        board_cache, quota, search_client, {AtsProvider.GREENHOUSE: greenhouse}
    )

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is not None
    assert result.apply_url == "https://boards.greenhouse.io/acme/jobs/1"
    assert quota.consume_calls == 0
    assert search_client.queries == []
    assert greenhouse.calls == [("acme", "Engineer")]


@pytest.mark.asyncio
async def test_board_cache_miss_locates_board_via_search_then_queries_it():
    board_cache = FakeBoardRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(
        results=[
            BraveSearchResult(
                url="https://acme.example.com", description="Acme's homepage."
            ),
            BraveSearchResult(
                url="https://boards.greenhouse.io/acme",
                description="Acme's careers board.",
            ),
        ]
    )
    greenhouse = FakeAtsBoardClient(
        AtsProvider.GREENHOUSE,
        result=ResolvedListingFields(
            apply_url="https://boards.greenhouse.io/acme/jobs/1",
            description="Full job description.",
        ),
    )
    resolver = AtsListingResolver(
        board_cache, quota, search_client, {AtsProvider.GREENHOUSE: greenhouse}
    )

    result = await resolver.resolve(company="Acme Corp", title="Backend Engineer")

    assert result is not None
    assert result.apply_url == "https://boards.greenhouse.io/acme/jobs/1"
    assert quota.consume_calls == 1
    assert len(search_client.queries) == 1
    assert greenhouse.calls == [("acme", "Backend Engineer")]


@pytest.mark.asyncio
async def test_discovered_board_is_saved_to_the_cache():
    board_cache = FakeBoardRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(
        results=[
            BraveSearchResult(
                url="https://jobs.lever.co/acme", description="Acme's board."
            )
        ]
    )
    lever = FakeAtsBoardClient(
        AtsProvider.LEVER,
        result=ResolvedListingFields(apply_url="https://x", description="y"),
    )
    resolver = AtsListingResolver(
        board_cache, quota, search_client, {AtsProvider.LEVER: lever}
    )

    await resolver.resolve(company="Acme Corp", title="Engineer")

    assert len(board_cache.saved) == 1
    assert board_cache.saved[0].normalized_company == normalize_text("Acme Corp")
    assert board_cache.saved[0].provider == AtsProvider.LEVER
    assert board_cache.saved[0].board_token == "acme"


@pytest.mark.asyncio
async def test_linkedin_and_indeed_results_are_never_recognized_as_a_board():
    board_cache = FakeBoardRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(
        results=[
            BraveSearchResult(
                url="https://www.linkedin.com/jobs/view/1", description="LinkedIn."
            ),
            BraveSearchResult(
                url="https://www.indeed.com/viewjob?jk=1", description="Indeed."
            ),
        ]
    )
    resolver = AtsListingResolver(board_cache, quota, search_client, {})

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None
    assert board_cache.saved == []


@pytest.mark.asyncio
async def test_quota_exhaustion_degrades_to_none_without_calling_search():
    board_cache = FakeBoardRepository()
    quota = FakeQuota(allowed=False)
    search_client = FakeSearchClient()
    resolver = AtsListingResolver(board_cache, quota, search_client, {})

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None
    assert search_client.queries == []


@pytest.mark.asyncio
async def test_no_recognized_board_in_search_results_returns_none():
    board_cache = FakeBoardRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(
        results=[
            BraveSearchResult(
                url="https://acme.example.com", description="Acme's homepage."
            )
        ]
    )
    resolver = AtsListingResolver(board_cache, quota, search_client, {})

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None
    assert board_cache.saved == []


@pytest.mark.asyncio
async def test_search_client_error_degrades_to_none_instead_of_raising():
    board_cache = FakeBoardRepository()
    quota = FakeQuota(allowed=True)
    search_client = FakeSearchClient(error=ExternalServiceError("boom"))
    resolver = AtsListingResolver(board_cache, quota, search_client, {})

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None


@pytest.mark.asyncio
async def test_board_client_error_degrades_to_none_instead_of_raising():
    board_cache = FakeBoardRepository()
    board_cache.saved.append(
        ResolvedCompanyBoard(
            company="Acme Corp", provider=AtsProvider.ASHBY, board_token="acme"
        )
    )
    quota = FakeQuota()
    search_client = FakeSearchClient()
    ashby = FakeAtsBoardClient(
        AtsProvider.ASHBY, error=ExternalServiceError("ats down")
    )
    resolver = AtsListingResolver(
        board_cache, quota, search_client, {AtsProvider.ASHBY: ashby}
    )

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None


@pytest.mark.asyncio
async def test_no_board_client_configured_for_cached_provider_returns_none():
    board_cache = FakeBoardRepository()
    board_cache.saved.append(
        ResolvedCompanyBoard(
            company="Acme Corp", provider=AtsProvider.LEVER, board_token="acme"
        )
    )
    quota = FakeQuota()
    search_client = FakeSearchClient()
    resolver = AtsListingResolver(board_cache, quota, search_client, {})

    result = await resolver.resolve(company="Acme Corp", title="Engineer")

    assert result is None


@pytest.mark.asyncio
async def test_two_different_titles_at_the_same_company_each_get_their_own_lookup():
    """The board is cached, but the per-listing apply_url/description is
    not -- two different roles at the same company must not collapse
    onto whichever one was resolved first."""
    board_cache = FakeBoardRepository()
    board_cache.saved.append(
        ResolvedCompanyBoard(
            company="Acme Corp", provider=AtsProvider.GREENHOUSE, board_token="acme"
        )
    )
    quota = FakeQuota()
    search_client = FakeSearchClient()

    class TitleAwareGreenhouse:
        provider = AtsProvider.GREENHOUSE

        async def find_job(
            self, *, board_token: str, title: str
        ) -> ResolvedListingFields:
            return ResolvedListingFields(
                apply_url=f"https://boards.greenhouse.io/{board_token}/{title}",
                description=f"Description for {title}.",
            )

    resolver = AtsListingResolver(
        board_cache,
        quota,
        search_client,
        {AtsProvider.GREENHOUSE: TitleAwareGreenhouse()},
    )

    backend = await resolver.resolve(company="Acme Corp", title="Backend Engineer")
    frontend = await resolver.resolve(company="Acme Corp", title="Frontend Engineer")

    assert backend is not None and frontend is not None
    assert backend.apply_url != frontend.apply_url
    assert backend.description != frontend.description
    # The board itself was only ever cached once.
    assert len(board_cache.saved) == 1
