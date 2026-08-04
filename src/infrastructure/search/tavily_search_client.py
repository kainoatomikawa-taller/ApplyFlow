"""Tavily implementation of the raw search-API call backing `AtsListingResolver`.

Replaced Brave Search, which withdrew its free tier. The shape of the job is
unchanged — one HTTP call, structured JSON in, `WebSearchResult`s out, no
scraping of result pages — but Tavily's API differs from Brave's in three ways
that matter to anyone reading this alongside the git history:

* **POST, not GET.** The query travels in a JSON body rather than a query string.
  That is incidentally better for this project's URL-hygiene rule (ADR 0003): a
  search term can be a person's name, and a body is not logged by intermediaries
  the way a URL is.
* **Bearer auth.** The key goes in an `Authorization` header, so it never appears
  in a URL or a body — the arrangement ADR 0003 prefers and which Adzuna alone
  cannot offer.
* **`content`, not `description`.** Tavily returns a longer text snippet per
  result. `AtsListingResolver` reads it the same way, to recognize an ATS board
  from the snippet rather than by fetching the page.

The result type is deliberately named for what it is rather than for the vendor
that produced it. Brave's departure cascaded a rename through every consumer;
`WebSearchResult` means the next provider swap touches this file and its test.

Rate limits/retries: mirrors `AdzunaJobAggregatorClient`'s retry loop — this
class owns retry/backoff policy (`search_api_max_retries` /
`search_api_retry_base_delay_seconds` / `search_api_retry_max_delay_seconds`),
retrying only transient failures (429 rate limits, 5xxs, connection errors). A
429's `Retry-After` header, when present, overrides the computed backoff delay.
Non-transient errors (401/403/400/404) surface immediately as an
`ExternalServiceError` naming what went wrong.

Quota: Tavily's free allowance is metered and small, so `DailySearchQuota` and
the resolver's board cache in front of this client are load-bearing rather than
nice-to-have — a resolved company board is cached so the same lookup is not paid
for twice. See `AtsListingResolver`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from src.application.exceptions import ExternalServiceError
from src.infrastructure.config import Settings

logger = logging.getLogger(__name__)

#: HTTP status codes worth retrying — rate limit plus anything 5xx.
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


@dataclass(frozen=True)
class WebSearchResult:
    """One organic web result: where it points, and the snippet describing it."""

    url: str
    description: str


class TavilySearchClient:
    def __init__(
        self, settings: Settings, http_client: httpx.AsyncClient | None = None
    ) -> None:
        api_key = settings.search_api_key.get_secret_value()
        if not api_key:
            raise ExternalServiceError(
                "SEARCH_API_KEY is not configured; cannot authenticate to "
                "the search API."
            )
        self._api_key = api_key
        self._base_url = settings.search_api_base_url
        self._max_retries = settings.search_api_max_retries
        self._retry_base_delay = settings.search_api_retry_base_delay_seconds
        self._retry_max_delay = settings.search_api_retry_max_delay_seconds
        # httpx owns no retries of its own — this class is the single
        # source of truth for retry/backoff (see module docstring).
        self._client = http_client or httpx.AsyncClient(timeout=30.0)

    async def search_many(self, query: str, count: int = 5) -> list[WebSearchResult]:
        """Return up to `count` organic web results for `query`, in ranking
        order. An empty list means the provider returned no results — never an
        error.

        `search_depth` is left at Tavily's cheaper "basic" setting: this client
        exists to recognize which ATS a company's board lives on, which the first
        page of ordinary results answers. "advanced" costs more credits per call
        for depth that would not change the answer.
        """
        data = await self._post_with_retry(
            self._base_url,
            {"query": query, "max_results": count, "search_depth": "basic"},
        )

        results = data.get("results") or []
        if not isinstance(results, list):
            return []

        mapped: list[WebSearchResult] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = _as_str(item.get("url"))
            # `content` is Tavily's snippet field; `description` is accepted as a
            # fallback so a response shaped like the old provider's still maps.
            description = _as_str(item.get("content")) or _as_str(
                item.get("description")
            )
            if url and description:
                mapped.append(WebSearchResult(url=url, description=description))
        return mapped

    async def _post_with_retry(
        self, url: str, payload: dict[str, str | int]
    ) -> dict[str, Any]:
        max_attempts = self._max_retries + 1
        last_exc: Exception | None = None
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == max_attempts:
                    break
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "tavily search request failed with %s (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    type(exc).__name__,
                    attempt,
                    max_attempts,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code < 400:
                result: dict[str, Any] = response.json()
                return result

            if response.status_code not in _RETRYABLE_STATUS_CODES:
                raise ExternalServiceError(
                    f"Tavily search request failed with non-retryable status "
                    f"{response.status_code}: {response.text}"
                )

            last_exc = ExternalServiceError(
                f"Tavily search request failed with status {response.status_code}"
            )
            if attempt == max_attempts:
                break
            delay = self._retry_after_delay(response) or self._backoff_delay(attempt)
            logger.warning(
                "tavily search request failed with status %d (attempt %d/%d), "
                "retrying in %.1fs",
                response.status_code,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

        raise ExternalServiceError(
            f"Tavily search request failed after {max_attempts} attempt(s) due "
            f"to a transient error: {last_exc}"
        ) from last_exc

    def _retry_after_delay(self, response: httpx.Response) -> float | None:
        header = response.headers.get("Retry-After")
        if header is None:
            return None
        try:
            return min(float(header), self._retry_max_delay)
        except ValueError:
            return None

    def _backoff_delay(self, attempt: int) -> float:
        delay = self._retry_base_delay * (2 ** (attempt - 1))
        return float(min(delay, self._retry_max_delay))


def _as_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
