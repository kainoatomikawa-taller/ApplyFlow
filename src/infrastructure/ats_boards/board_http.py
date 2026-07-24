"""get_json_or_none — shared GET-with-retry helper for the Greenhouse/
Lever/Ashby board clients.

Same retry/backoff shape already used by `AdzunaJobAggregatorClient` and
`BraveSearchClient` (retry only 429/5xx/connection errors, honor a 429's
`Retry-After` header, exponential backoff capped at a max delay) —
extracted here rather than duplicated a third time, since all three ATS
clients need the identical loop. Those two pre-existing clients are left
as-is; this helper is additive, not a refactor of working code.

A 404 is treated as a routine "no board under this token" outcome (a
discovered board reference turning out to be stale, or wrong) and returns
`None` instead of raising — every other non-2xx status behaves exactly as
in the clients above.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from src.application.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


async def get_json_or_none(
    client: httpx.AsyncClient,
    url: str,
    *,
    service_name: str,
    params: dict[str, str] | None = None,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    retry_max_delay: float = 20.0,
) -> Any | None:
    """GET `url`, retrying transient failures, and return the parsed JSON
    body (an object or array, whatever the endpoint returns) — or `None`
    if the endpoint responded 404."""
    max_attempts = max_retries + 1
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = _backoff_delay(attempt, retry_base_delay, retry_max_delay)
            logger.warning(
                "%s board request failed with %s (attempt %d/%d), "
                "retrying in %.1fs: %s",
                service_name,
                type(exc).__name__,
                attempt,
                max_attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
            continue

        if response.status_code == 404:
            return None

        if response.status_code < 400:
            result: Any = response.json()
            return result

        if response.status_code not in _RETRYABLE_STATUS_CODES:
            raise ExternalServiceError(
                f"{service_name} board request failed with non-retryable "
                f"status {response.status_code}: {response.text}"
            )

        last_exc = ExternalServiceError(
            f"{service_name} board request failed with status "
            f"{response.status_code}"
        )
        if attempt == max_attempts:
            break
        delay = _retry_after_delay(response, retry_max_delay) or _backoff_delay(
            attempt, retry_base_delay, retry_max_delay
        )
        logger.warning(
            "%s board request failed with status %d (attempt %d/%d), "
            "retrying in %.1fs",
            service_name,
            response.status_code,
            attempt,
            max_attempts,
            delay,
        )
        await asyncio.sleep(delay)

    raise ExternalServiceError(
        f"{service_name} board request failed after {max_attempts} "
        f"attempt(s) due to a transient error: {last_exc}"
    ) from last_exc


def _retry_after_delay(
    response: httpx.Response, retry_max_delay: float
) -> float | None:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return min(float(header), retry_max_delay)
    except ValueError:
        return None


def _backoff_delay(
    attempt: int, retry_base_delay: float, retry_max_delay: float
) -> float:
    delay = retry_base_delay * (2 ** (attempt - 1))
    return float(min(delay, retry_max_delay))
