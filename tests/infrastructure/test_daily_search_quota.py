"""Tests for DailySearchQuota — the Redis-backed daily counter behind
SearchApiListingResolver's graceful degradation.

No real Redis connection: a small in-memory fake stands in for
`redis.asyncio.Redis`, since this class only calls `incr`/`expire`.
"""

from __future__ import annotations

import pytest

from src.infrastructure.search.daily_search_quota import DailySearchQuota


class FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expired_keys: list[tuple[str, int]] = []

    async def incr(self, name: str) -> int:
        self.counters[name] = self.counters.get(name, 0) + 1
        return self.counters[name]

    async def expire(self, name: str, time: int) -> bool:
        self.expired_keys.append((name, time))
        return True


@pytest.mark.asyncio
async def test_try_consume_allows_calls_within_the_daily_limit():
    quota = DailySearchQuota(FakeRedis(), daily_limit=3)

    assert await quota.try_consume() is True
    assert await quota.try_consume() is True
    assert await quota.try_consume() is True


@pytest.mark.asyncio
async def test_try_consume_returns_false_once_the_limit_is_exceeded():
    quota = DailySearchQuota(FakeRedis(), daily_limit=2)

    assert await quota.try_consume() is True
    assert await quota.try_consume() is True
    assert await quota.try_consume() is False
    # Still tracks (doesn't error) on further calls past the limit.
    assert await quota.try_consume() is False


@pytest.mark.asyncio
async def test_expiry_is_set_only_on_the_first_increment_of_the_day():
    redis_client = FakeRedis()
    quota = DailySearchQuota(redis_client, daily_limit=100)

    await quota.try_consume()
    await quota.try_consume()

    assert len(redis_client.expired_keys) == 1
    _, ttl_seconds = redis_client.expired_keys[0]
    assert ttl_seconds == 24 * 60 * 60


@pytest.mark.asyncio
async def test_separate_quota_instances_share_the_same_counter_via_redis():
    """Two resolver instances (e.g. different worker processes) sharing the
    same Redis backend must see the same daily count."""
    redis_client = FakeRedis()
    quota_a = DailySearchQuota(redis_client, daily_limit=1)
    quota_b = DailySearchQuota(redis_client, daily_limit=1)

    assert await quota_a.try_consume() is True
    assert await quota_b.try_consume() is False
