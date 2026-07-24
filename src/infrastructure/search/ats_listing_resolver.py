"""AtsListingResolver — the ListingResolverPort implementation backing
`IngestAggregatorJobs` by resolving against a company's own ATS board
(Greenhouse/Lever/Ashby public feed) rather than trusting a generic web
search snippet.

Two genuinely different things are involved here, at two different costs:
  - WHICH board a company posts through (`ResolvedCompanyBoardRepository`)
    is the expensive, quota-limited thing to discover — finding it costs
    one Brave Search API call, so once found it is cached permanently per
    company and that company is never searched again (see
    `DailySearchQuota`, a ~100/day free-tier budget).
  - The job-specific apply URL + full description is NOT cached — every
    listing gets its own lookup against the (free, unauthenticated,
    already-known) board, so two different open roles at the same company
    each get their own correct apply link and description instead of
    silently reusing whichever role happened to be resolved first.

Only Greenhouse/Lever/Ashby board URLs are ever recognized (see
`identify_ats_board` — an allowlist, not a blocklist), and the locating
search query itself is restricted to those three domains. A LinkedIn or
Indeed result is therefore never a candidate to resolve through at either
stage — it simply cannot match, exactly as if the search had found
nothing there.

Any failure along the way — quota exhausted, no board found, a board
found but this title isn't listed on it, a transient HTTP error from
Brave or from the ATS itself — degrades to `None` rather than raising:
one company's unresolvable listing must never abort the rest of an
ingestion run.
"""

from __future__ import annotations

import logging

from src.application.exceptions import ExternalServiceError
from src.application.ports.ats_board_client_port import AtsBoardClientPort
from src.application.ports.listing_resolver_port import (
    ListingResolverPort,
    ResolvedListingFields,
)
from src.domain.entities.resolved_company_board import ResolvedCompanyBoard
from src.domain.repositories.resolved_company_board_repository import (
    ResolvedCompanyBoardRepository,
)
from src.domain.services.ats_board_locator import identify_ats_board
from src.domain.services.text_normalization import normalize_text
from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.search.brave_search_client import BraveSearchClient
from src.infrastructure.search.daily_search_quota import DailySearchQuota

logger = logging.getLogger(__name__)

#: Restricts the locate-the-board search to the three supported ATS
#: platforms via Brave's `site:` operator — the search-side half of the
#: LinkedIn/Indeed exclusion; `identify_ats_board` is the structural half
#: that holds even if a result slips past this filter.
_BOARD_SITE_FILTER = (
    "(site:boards.greenhouse.io OR site:job-boards.greenhouse.io "
    "OR site:jobs.lever.co OR site:jobs.ashbyhq.com)"
)


class AtsListingResolver(ListingResolverPort):
    def __init__(
        self,
        board_cache: ResolvedCompanyBoardRepository,
        quota: DailySearchQuota,
        search_client: BraveSearchClient,
        board_clients: dict[AtsProvider, AtsBoardClientPort],
        result_count: int = 5,
    ) -> None:
        self._board_cache = board_cache
        self._quota = quota
        self._search_client = search_client
        self._board_clients = board_clients
        self._result_count = result_count

    async def resolve(
        self, *, company: str, title: str
    ) -> ResolvedListingFields | None:
        board = await self._board_cache.get_by_normalized_company(
            normalize_text(company)
        )
        if board is None:
            board = await self._locate_board(company)
            if board is None:
                return None

        board_client = self._board_clients.get(board.provider)
        if board_client is None:
            logger.warning(
                "no AtsBoardClientPort configured for provider=%r", board.provider
            )
            return None

        try:
            return await board_client.find_job(
                board_token=board.board_token, title=title
            )
        except ExternalServiceError as exc:
            logger.warning(
                "ATS board request failed for company=%r provider=%r: %s",
                company,
                board.provider,
                exc,
            )
            return None

    async def _locate_board(self, company: str) -> ResolvedCompanyBoard | None:
        if not await self._quota.try_consume():
            logger.warning(
                "search API daily quota exhausted; skipping board discovery "
                "for company=%r",
                company,
            )
            return None

        try:
            results = await self._search_client.search_many(
                f'"{company}" careers {_BOARD_SITE_FILTER}',
                count=self._result_count,
            )
        except ExternalServiceError as exc:
            logger.warning(
                "search API request failed for company=%r: %s", company, exc
            )
            return None

        for result in results:
            reference = identify_ats_board(result.url)
            if reference is None:
                continue
            board = ResolvedCompanyBoard(
                company=company,
                provider=reference.provider,
                board_token=reference.board_token,
            )
            await self._board_cache.save(board)
            return board

        return None
