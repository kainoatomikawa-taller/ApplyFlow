"""Adzuna implementation of the JobAggregatorPort.

This is the only place in the codebase that knows Adzuna's request/response
shape — the mapping from its raw JSON onto `AggregatorJobListing` (and, in
turn, `JobPosting` via `IngestAggregatorJobs`) all happens here so the
application layer never sees an Adzuna-specific field name.

Authentication is Adzuna's `app_id`/`app_key` pair, both sourced from the
Epic 00 config layer (`Settings.job_aggregator_app_id` /
`.job_aggregator_api_key`), passed as query parameters per Adzuna's API.

Pagination: Adzuna's `/search/{page}` endpoint is 1-indexed and reports a
total `count`; `has_more` is derived by comparing how many results have
been seen so far against that count, so a caller walking pages via
`IngestAggregatorJobs` stops exactly at the last page instead of guessing
from a full page of results.

Rate limits/retries: mirrors `AnthropicLlmClient`'s retry loop — this class
owns retry/backoff policy (`JOB_AGGREGATOR_MAX_RETRIES` /
`_RETRY_BASE_DELAY_SECONDS` / `_RETRY_MAX_DELAY_SECONDS`), retrying only
transient failures (429 rate limits, 5xxs, connection errors). A 429's
`Retry-After` header, when present, overrides the computed backoff delay
since Adzuna knows better than we do how long its own limit window is.
Non-transient errors (401/403/400/404) surface immediately as an
`ExternalServiceError` naming what went wrong.

Salary: Adzuna reports `salary_min`/`salary_max` as annualized figures (it
has no separate hourly-rate field in its public API), so every mapped
`SalaryRange` uses `SalaryPeriod.YEARLY`. Currency is inferred from the
configured search country rather than returned by the API.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

import httpx

from src.application.exceptions import ExternalServiceError
from src.application.ports.job_aggregator_port import (
    AggregatorJobListing,
    AggregatorPage,
    JobAggregatorPort,
)
from src.domain.value_objects.salary_range import SalaryPeriod, SalaryRange
from src.infrastructure.config import Settings

logger = logging.getLogger(__name__)

#: HTTP status codes worth retrying — rate limit plus anything 5xx.
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

#: Adzuna doesn't return a currency on each listing — it's implied by which
#: country's endpoint answered the search. Falls back to USD for any
#: Adzuna-supported country not listed here.
_COUNTRY_CURRENCY: dict[str, str] = {
    "us": "USD",
    "gb": "GBP",
    "at": "EUR",
    "au": "AUD",
    "be": "EUR",
    "br": "BRL",
    "ca": "CAD",
    "ch": "CHF",
    "de": "EUR",
    "es": "EUR",
    "fr": "EUR",
    "in": "INR",
    "it": "EUR",
    "mx": "MXN",
    "nl": "EUR",
    "nz": "NZD",
    "pl": "PLN",
    "sg": "SGD",
    "za": "ZAR",
}


class AdzunaJobAggregatorClient(JobAggregatorPort):
    def __init__(
        self, settings: Settings, http_client: httpx.AsyncClient | None = None
    ) -> None:
        app_id = settings.job_aggregator_app_id
        app_key = settings.job_aggregator_api_key.get_secret_value()
        if not app_id or not app_key:
            raise ExternalServiceError(
                "JOB_AGGREGATOR_APP_ID/JOB_AGGREGATOR_API_KEY are not "
                "configured; cannot authenticate to Adzuna."
            )
        self._app_id = app_id
        self._app_key = app_key
        self._base_url = settings.job_aggregator_base_url
        self._country = settings.job_aggregator_country
        self._results_per_page = settings.job_aggregator_results_per_page
        self._max_retries = settings.job_aggregator_max_retries
        self._retry_base_delay = settings.job_aggregator_retry_base_delay_seconds
        self._retry_max_delay = settings.job_aggregator_retry_max_delay_seconds
        # httpx owns no retries of its own — this class is the single
        # source of truth for retry/backoff (see module docstring).
        self._client = http_client or httpx.AsyncClient(timeout=30.0)

    @property
    def source_name(self) -> str:
        return "adzuna"

    async def fetch_page(
        self, *, keywords: str, location: str | None, page: int
    ) -> AggregatorPage:
        params: dict[str, str | int] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "results_per_page": self._results_per_page,
            "what": keywords,
            "content-type": "application/json",
        }
        if location:
            params["where"] = location

        data = await self._get_with_retry(
            f"{self._base_url}/{self._country}/search/{page}", params
        )

        results = data.get("results")
        listings = [
            self._map_listing(result)
            for result in (results if isinstance(results, list) else [])
        ]

        total_count = data.get("count")
        seen_so_far = page * self._results_per_page
        has_more = isinstance(total_count, int) and seen_so_far < total_count

        return AggregatorPage(listings=listings, has_more=has_more)

    async def _get_with_retry(
        self, url: str, params: dict[str, str | int]
    ) -> dict[str, Any]:
        max_attempts = self._max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == max_attempts:
                    break
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "adzuna request failed with %s (attempt %d/%d), "
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
                    f"Adzuna request failed with non-retryable status "
                    f"{response.status_code}: {response.text}"
                )

            last_exc = ExternalServiceError(
                f"Adzuna request failed with status {response.status_code}"
            )
            if attempt == max_attempts:
                break
            delay = self._retry_after_delay(response) or self._backoff_delay(attempt)
            logger.warning(
                "adzuna request failed with status %d (attempt %d/%d), "
                "retrying in %.1fs",
                response.status_code,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

        raise ExternalServiceError(
            f"Adzuna request failed after {max_attempts} attempt(s) due to a "
            f"transient error: {last_exc}"
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

    def _map_listing(self, result: dict[str, Any]) -> AggregatorJobListing:
        title = _as_str(result.get("title")) or "Untitled"
        description = _as_str(result.get("description")) or ""
        location = _as_str((result.get("location") or {}).get("display_name"))

        return AggregatorJobListing(
            external_id=_as_str(result.get("id")) or "",
            company=_as_str((result.get("company") or {}).get("display_name"))
            or "Unknown",
            title=title,
            apply_url=_as_str(result.get("redirect_url")) or "",
            description=description,
            is_remote=_looks_remote(title, location, description),
            location=location,
            salary=self._map_salary(result),
            posted_at=_as_date(result.get("created")),
        )

    def _map_salary(self, result: dict[str, Any]) -> SalaryRange | None:
        min_amount = _as_float(result.get("salary_min"))
        max_amount = _as_float(result.get("salary_max"))
        if min_amount is None and max_amount is None:
            return None
        return SalaryRange(
            currency=_COUNTRY_CURRENCY.get(self._country.lower(), "USD"),
            period=SalaryPeriod.YEARLY,
            min_amount=min_amount,
            max_amount=max_amount,
        )


def _as_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _as_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip()).date()
    except ValueError:
        return None


def _looks_remote(title: str, location: str | None, description: str) -> bool:
    """Adzuna has no dedicated "remote" flag in its public API — infer it
    from the same signals a human skimming a listing would use."""
    haystack = " ".join(filter(None, [title, location, description])).lower()
    return "remote" in haystack
