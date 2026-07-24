"""Brave Search implementation of the raw search-API call backing
`SearchApiListingResolver`.

Authenticates with Brave's single `X-Subscription-Token` header, sourced
from the Epic 00 config layer (`Settings.search_api_key`). This class only
performs the one HTTP call and maps Brave's structured JSON response onto
`BraveSearchResult` — it never scrapes the raw HTML of a result page, only
reads the `url`/`description` fields Brave's Web Search API already
returns as structured JSON.

Rate limits/retries: mirrors `AdzunaJobAggregatorClient`'s retry loop —
this class owns retry/backoff policy (`search_api_max_retries` /
`search_api_retry_base_delay_seconds` / `search_api_retry_max_delay_seconds`),
retrying only transient failures (429 rate limits, 5xxs, connection
errors). A 429's `Retry-After` header, when present, overrides the
computed backoff delay. Non-transient errors (401/403/400/404) surface
immediately as an `ExternalServiceError` naming what went wrong.
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
class BraveSearchResult:
    """The top organic web result for a query."""

    url: str
    description: str


class BraveSearchClient:
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

    async def search(self, query: str) -> BraveSearchResult | None:
        """Return the top organic web result for `query`, or None if Brave
        returned no results."""
        data = await self._get_with_retry(
            self._base_url, {"q": query, "count": 1}
        )

        results = ((data.get("web") or {}).get("results")) or []
        if not isinstance(results, list) or not results:
            return None

        top = results[0]
        url = _as_str(top.get("url")) if isinstance(top, dict) else None
        description = _as_str(top.get("description")) if isinstance(top, dict) else None
        if not url or not description:
            return None

        return BraveSearchResult(url=url, description=description)

    async def _get_with_retry(
        self, url: str, params: dict[str, str | int]
    ) -> dict[str, Any]:
        max_attempts = self._max_retries + 1
        last_exc: Exception | None = None
        headers = {"X-Subscription-Token": self._api_key, "Accept": "application/json"}

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == max_attempts:
                    break
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "brave search request failed with %s (attempt %d/%d), "
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
                    f"Brave search request failed with non-retryable status "
                    f"{response.status_code}: {response.text}"
                )

            last_exc = ExternalServiceError(
                f"Brave search request failed with status {response.status_code}"
            )
            if attempt == max_attempts:
                break
            delay = self._retry_after_delay(response) or self._backoff_delay(attempt)
            logger.warning(
                "brave search request failed with status %d (attempt %d/%d), "
                "retrying in %.1fs",
                response.status_code,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

        raise ExternalServiceError(
            f"Brave search request failed after {max_attempts} attempt(s) due "
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
