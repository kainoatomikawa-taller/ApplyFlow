"""HttpApplyUrlChecker — ApplyUrlCheckerPort backed by a direct HTTP
probe against a posting's own apply_url.

Tries HEAD first (cheap, no response body) and falls back to GET only
when a server rejects HEAD specifically (405 Method Not Allowed), since
some careers pages/ATS boards don't implement HEAD at all. Redirects are
followed — an apply link that redirects to a real page is exactly as
"reachable" as one that doesn't.

Deliberately does NOT retry within a single call the way
`AdzunaJobAggregatorClient`/`BraveSearchClient`/the ATS board clients do:
robustness against a one-off blip here comes from
`JobPosting.apply_link_check`'s consecutive-failure threshold, spread
across separate scheduled sweep runs, rather than from hammering a server
that may already be struggling.
"""

from __future__ import annotations

import httpx

from src.application.ports.apply_url_checker_port import ApplyUrlCheckerPort
from src.domain.value_objects.link_check_outcome import LinkCheckOutcome
from src.infrastructure.config import Settings

#: Status codes a server uses to unambiguously assert a resource is gone.
_CONFIRMED_DEAD_STATUS_CODES = frozenset({404, 410})


class HttpApplyUrlChecker(ApplyUrlCheckerPort):
    def __init__(
        self, settings: Settings, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._client = http_client or httpx.AsyncClient(
            timeout=settings.apply_url_check_timeout_seconds, follow_redirects=True
        )

    async def check(self, url: str) -> LinkCheckOutcome:
        try:
            response = await self._client.head(url)
            if response.status_code == 405:
                response = await self._client.get(url)
        except httpx.HTTPError:
            return LinkCheckOutcome.TRANSIENT_FAILURE

        if response.status_code in _CONFIRMED_DEAD_STATUS_CODES:
            return LinkCheckOutcome.CONFIRMED_DEAD
        if response.status_code >= 500:
            return LinkCheckOutcome.TRANSIENT_FAILURE
        return LinkCheckOutcome.REACHABLE
