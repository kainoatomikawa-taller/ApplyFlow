"""Tests for BraveSearchClient — the Brave implementation of the raw
search-API call backing AtsListingResolver.

No network calls: `httpx.AsyncClient` is given a `MockTransport` that
simulates Brave's response shape (including rate-limit/error responses),
so these run offline and deterministically.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from src.application.exceptions import ExternalServiceError
from src.infrastructure.config import Settings
from src.infrastructure.search.brave_search_client import BraveSearchClient


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "search_api_key": SecretStr("test-search-key"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _client_with_handler(
    handler, **settings_overrides: object
) -> BraveSearchClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return BraveSearchClient(_settings(**settings_overrides), http_client=http_client)


@pytest.fixture
def no_sleep(monkeypatch):
    """Patch out asyncio.sleep so retry-backoff tests don't wait for real."""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.search.brave_search_client.asyncio.sleep", mock
    )
    return mock


def test_missing_api_key_fails_closed():
    with pytest.raises(ExternalServiceError, match="SEARCH_API_KEY"):
        BraveSearchClient(_settings(search_api_key=SecretStr("")))


# ---- request construction ---------------------------------------------


@pytest.mark.asyncio
async def test_search_many_sends_the_subscription_token_header_and_query():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"web": {"results": []}})

    client = _client_with_handler(handler)
    await client.search_many("Acme Corp careers apply")

    assert captured["headers"]["x-subscription-token"] == "test-search-key"
    assert captured["params"]["q"] == "Acme Corp careers apply"


@pytest.mark.asyncio
async def test_search_many_sends_the_requested_count():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"web": {"results": []}})

    client = _client_with_handler(handler)
    await client.search_many("acme careers", count=7)

    assert captured["params"]["count"] == "7"


# ---- schema mapping ------------------------------------------------------


@pytest.mark.asyncio
async def test_search_many_maps_every_result_in_ranking_order():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://acme.example.com",
                            "description": "Acme's homepage.",
                        },
                        {
                            "url": "https://boards.greenhouse.io/acme",
                            "description": "Acme's careers board.",
                        },
                    ]
                }
            },
        )

    client = _client_with_handler(handler)
    results = await client.search_many("acme careers")

    assert [r.url for r in results] == [
        "https://acme.example.com",
        "https://boards.greenhouse.io/acme",
    ]
    assert results[1].description == "Acme's careers board."


@pytest.mark.asyncio
async def test_search_many_skips_results_missing_url_or_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"url": "https://acme.example.com"},
                        {"description": "no url here"},
                        {
                            "url": "https://boards.greenhouse.io/acme",
                            "description": "Acme's careers board.",
                        },
                    ]
                }
            },
        )

    client = _client_with_handler(handler)
    results = await client.search_many("acme careers")

    assert len(results) == 1
    assert results[0].url == "https://boards.greenhouse.io/acme"


@pytest.mark.asyncio
async def test_search_many_returns_empty_list_when_brave_has_no_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"web": {"results": []}})

    client = _client_with_handler(handler)
    results = await client.search_many("a company that does not exist")

    assert results == []


@pytest.mark.asyncio
async def test_search_many_handles_a_missing_web_key_without_crashing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = _client_with_handler(handler)
    results = await client.search_many("acme")

    assert results == []


# ---- rate limits / retries -------------------------------------------------


@pytest.mark.asyncio
async def test_retries_on_429_and_then_succeeds(no_sleep):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"web": {"results": []}})

    client = _client_with_handler(handler)
    results = await client.search_many("acme")

    assert results == []
    assert calls["count"] == 2
    no_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_after_header_overrides_computed_backoff(no_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")

    client = _client_with_handler(
        handler,
        search_api_max_retries=1,
        search_api_retry_base_delay_seconds=1.0,
    )
    with pytest.raises(ExternalServiceError):
        await client.search_many("acme")

    no_sleep.assert_awaited_once_with(7.0)


@pytest.mark.asyncio
async def test_non_retryable_status_surfaces_immediately(no_sleep):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, text="bad credentials")

    client = _client_with_handler(handler)

    with pytest.raises(ExternalServiceError, match="non-retryable status 401"):
        await client.search_many("acme")

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_exhausting_retries_raises_external_service_error(no_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    client = _client_with_handler(handler, search_api_max_retries=2)

    with pytest.raises(ExternalServiceError, match="after 3 attempt"):
        await client.search_many("acme")


@pytest.mark.asyncio
async def test_connection_errors_are_retried(no_sleep):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"web": {"results": []}})

    client = _client_with_handler(handler)
    await client.search_many("acme")

    assert calls["count"] == 2
