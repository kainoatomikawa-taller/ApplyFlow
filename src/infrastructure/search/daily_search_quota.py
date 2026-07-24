"""DailySearchQuota — tracks how many search-API queries have been made
today against `Settings.search_api_daily_quota`, so `AtsListingResolver`
can degrade gracefully (skip board discovery rather than erroring) once
the free tier's daily allowance is exhausted.

Backed by Redis (`Settings.redis_url`) rather than an in-process counter so
the limit holds across every worker process, and by a UTC-midnight-keyed
counter (rather than a fixed TTL from first use) so the quota resets at a
predictable wall-clock instant instead of 24h after whichever request
happened to run first.
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Protocol

_KEY_PREFIX = "search_api:quota:"
_SECONDS_PER_DAY = 24 * 60 * 60


class _RedisLike(Protocol):
    def incr(self, name: str) -> Awaitable[int]: ...
    def expire(self, name: str, time: int) -> Awaitable[bool]: ...


class DailySearchQuota:
    def __init__(self, redis_client: _RedisLike, daily_limit: int) -> None:
        self._redis = redis_client
        self._daily_limit = daily_limit

    async def try_consume(self) -> bool:
        """Atomically increment today's counter and report whether this
        call is within the daily limit. Returns False (without erroring)
        once the limit is reached, letting the caller degrade gracefully."""
        key = self._key_for_today()
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, _SECONDS_PER_DAY)
        return count <= self._daily_limit

    def _key_for_today(self) -> str:
        return f"{_KEY_PREFIX}{datetime.now(UTC).date().isoformat()}"
