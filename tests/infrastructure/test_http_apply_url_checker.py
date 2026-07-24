"""Tests for HttpApplyUrlChecker — ApplyUrlCheckerPort backed by a direct
HEAD/GET probe against a posting's apply_url.

No network calls: `httpx.AsyncClient` is given a `MockTransport`.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from src.domain.value_objects.link_check_outcome import LinkCheckOutcome
from src.infrastructure.config import Settings
from src.infrastructure.link_checking.http_apply_url_checker import (
    HttpApplyUrlChecker,
)


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"_env_file": None, "search_api_key": SecretStr("k")}
    defaults.update(overrides)
    return Settings(**defaults)


def _checker_with_handler(handler, **settings_overrides: object) -> HttpApplyUrlChecker:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return HttpApplyUrlChecker(_settings(**settings_overrides), http_client=http_client)


@pytest.mark.asyncio
async def test_2xx_is_reachable():
    checker = _checker_with_handler(lambda request: httpx.Response(200))
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.REACHABLE
    )


@pytest.mark.asyncio
async def test_3xx_is_reachable():
    checker = _checker_with_handler(lambda request: httpx.Response(301))
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.REACHABLE
    )


@pytest.mark.asyncio
async def test_404_is_confirmed_dead():
    checker = _checker_with_handler(lambda request: httpx.Response(404))
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.CONFIRMED_DEAD
    )


@pytest.mark.asyncio
async def test_410_is_confirmed_dead():
    checker = _checker_with_handler(lambda request: httpx.Response(410))
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.CONFIRMED_DEAD
    )


@pytest.mark.asyncio
async def test_500_is_transient_failure():
    checker = _checker_with_handler(lambda request: httpx.Response(503))
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.TRANSIENT_FAILURE
    )


@pytest.mark.asyncio
async def test_403_is_reachable_not_dead():
    """A page blocking non-browser user agents is not evidence the job is
    gone -- treating 403 as dead would wrongly exclude many live postings."""
    checker = _checker_with_handler(lambda request: httpx.Response(403))
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.REACHABLE
    )


@pytest.mark.asyncio
async def test_429_is_reachable_not_dead():
    checker = _checker_with_handler(lambda request: httpx.Response(429))
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.REACHABLE
    )


@pytest.mark.asyncio
async def test_connection_error_is_transient_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    checker = _checker_with_handler(handler)
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.TRANSIENT_FAILURE
    )


@pytest.mark.asyncio
async def test_timeout_is_transient_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=request)

    checker = _checker_with_handler(handler)
    assert await checker.check("https://acme.example.com/jobs/1") == (
        LinkCheckOutcome.TRANSIENT_FAILURE
    )


@pytest.mark.asyncio
async def test_falls_back_to_get_when_head_is_not_allowed():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200)

    checker = _checker_with_handler(handler)
    result = await checker.check("https://acme.example.com/jobs/1")

    assert result == LinkCheckOutcome.REACHABLE
    assert calls == ["HEAD", "GET"]
