"""Tests for AdzunaJobAggregatorClient — the Adzuna implementation of
JobAggregatorPort.

No network calls: `httpx.AsyncClient` is given a `MockTransport` that
simulates Adzuna's response shape (including rate-limit/error responses),
so these run offline and deterministically.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from src.application.exceptions import ExternalServiceError
from src.domain.value_objects.salary_range import SalaryPeriod
from src.infrastructure.config import Settings
from src.infrastructure.job_aggregators.adzuna_client import AdzunaJobAggregatorClient


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "job_aggregator_app_id": "test-app-id",
        "job_aggregator_api_key": SecretStr("test-app-key"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _result(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id": "123456",
        "title": "Backend Engineer",
        "company": {"display_name": "Acme Corp"},
        "location": {"display_name": "New York, NY"},
        "description": "Build things.",
        "redirect_url": "https://www.adzuna.com/details/123456",
        "salary_min": 120000.0,
        "salary_max": 160000.0,
        "created": "2026-07-20T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def _client_with_handler(
    handler, **settings_overrides: object
) -> AdzunaJobAggregatorClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return AdzunaJobAggregatorClient(
        _settings(**settings_overrides), http_client=http_client
    )


@pytest.fixture
def no_sleep(monkeypatch):
    """Patch out asyncio.sleep so retry-backoff tests don't wait for real."""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.job_aggregators.adzuna_client.asyncio.sleep", mock
    )
    return mock


def test_missing_app_id_fails_closed():
    with pytest.raises(ExternalServiceError, match="JOB_AGGREGATOR"):
        AdzunaJobAggregatorClient(_settings(job_aggregator_app_id=""))


def test_missing_app_key_fails_closed():
    with pytest.raises(ExternalServiceError, match="JOB_AGGREGATOR"):
        AdzunaJobAggregatorClient(_settings(job_aggregator_api_key=SecretStr("")))


def test_source_name_is_adzuna():
    client = _client_with_handler(lambda request: httpx.Response(200, json={}))
    assert client.source_name == "adzuna"


# ---- request construction ---------------------------------------------


@pytest.mark.asyncio
async def test_fetch_page_sends_credentials_and_query_as_params():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"results": [], "count": 0})

    client = _client_with_handler(handler)
    await client.fetch_page(keywords="engineer", location="NYC", page=1)

    assert "/us/search/1" in captured["url"]
    assert captured["params"]["app_id"] == "test-app-id"
    assert captured["params"]["app_key"] == "test-app-key"
    assert captured["params"]["what"] == "engineer"
    assert captured["params"]["where"] == "NYC"
    assert captured["params"]["results_per_page"] == "50"


@pytest.mark.asyncio
async def test_fetch_page_omits_where_when_no_location_given():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"results": [], "count": 0})

    client = _client_with_handler(handler)
    await client.fetch_page(keywords="engineer", location=None, page=1)

    assert "where" not in captured["params"]


# ---- schema mapping (the point of this ticket) --------------------------


@pytest.mark.asyncio
async def test_fetch_page_maps_adzuna_fields_onto_the_internal_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [_result()], "count": 1})

    client = _client_with_handler(handler)
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    listing = page.listings[0]
    assert listing.external_id == "123456"
    assert listing.company == "Acme Corp"
    assert listing.title == "Backend Engineer"
    assert listing.apply_url == "https://www.adzuna.com/details/123456"
    assert listing.description == "Build things."
    assert listing.location == "New York, NY"
    assert listing.salary is not None
    assert listing.salary.currency == "USD"
    assert listing.salary.period == SalaryPeriod.YEARLY
    assert listing.salary.min_amount == 120000.0
    assert listing.salary.max_amount == 160000.0
    assert listing.posted_at == date(2026, 7, 20)


@pytest.mark.asyncio
async def test_missing_salary_fields_yield_no_salary_range():
    def handler(request: httpx.Request) -> httpx.Response:
        result = _result()
        del result["salary_min"]
        del result["salary_max"]
        return httpx.Response(200, json={"results": [result], "count": 1})

    client = _client_with_handler(handler)
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    assert page.listings[0].salary is None


@pytest.mark.asyncio
async def test_remote_is_inferred_from_title_location_or_description():
    def handler(request: httpx.Request) -> httpx.Response:
        result = _result(title="Remote Backend Engineer")
        return httpx.Response(200, json={"results": [result], "count": 1})

    client = _client_with_handler(handler)
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    assert page.listings[0].is_remote is True


@pytest.mark.asyncio
async def test_onsite_listing_is_not_marked_remote():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [_result()], "count": 1})

    client = _client_with_handler(handler)
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    assert page.listings[0].is_remote is False


@pytest.mark.asyncio
async def test_currency_follows_the_configured_country():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [_result()], "count": 1})

    client = _client_with_handler(handler, job_aggregator_country="gb")
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    assert page.listings[0].salary.currency == "GBP"


@pytest.mark.asyncio
async def test_missing_optional_fields_do_not_crash_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        sparse = {"id": "1", "title": "Engineer"}
        return httpx.Response(200, json={"results": [sparse], "count": 1})

    client = _client_with_handler(handler)
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    listing = page.listings[0]
    assert listing.company == "Unknown"
    assert listing.apply_url == ""
    assert listing.location is None
    assert listing.salary is None
    assert listing.posted_at is None


# ---- pagination -----------------------------------------------------------


@pytest.mark.asyncio
async def test_has_more_true_when_more_results_remain():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [_result()], "count": 200})

    client = _client_with_handler(handler, job_aggregator_results_per_page=50)
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    assert page.has_more is True


@pytest.mark.asyncio
async def test_has_more_false_on_the_last_page():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [_result()], "count": 10})

    client = _client_with_handler(handler, job_aggregator_results_per_page=50)
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    assert page.has_more is False


@pytest.mark.asyncio
async def test_requests_the_correct_page_number_in_the_url():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"results": [], "count": 0})

    client = _client_with_handler(handler)
    await client.fetch_page(keywords="engineer", location=None, page=3)

    assert "/search/3" in captured["url"]


# ---- rate limits / retries (the point of this ticket) ---------------------


@pytest.mark.asyncio
async def test_retries_on_429_and_then_succeeds(no_sleep):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"results": [], "count": 0})

    client = _client_with_handler(handler)
    page = await client.fetch_page(keywords="engineer", location=None, page=1)

    assert page.listings == []
    assert calls["count"] == 2
    no_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_after_header_overrides_computed_backoff(no_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")

    client = _client_with_handler(
        handler,
        job_aggregator_max_retries=1,
        job_aggregator_retry_base_delay_seconds=1.0,
    )
    with pytest.raises(ExternalServiceError):
        await client.fetch_page(keywords="engineer", location=None, page=1)

    no_sleep.assert_awaited_once_with(7.0)


@pytest.mark.asyncio
async def test_retries_on_5xx_errors(no_sleep):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"results": [], "count": 0})

    client = _client_with_handler(handler)
    await client.fetch_page(keywords="engineer", location=None, page=1)

    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_non_retryable_status_surfaces_immediately(no_sleep):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, text="bad credentials")

    client = _client_with_handler(handler)

    with pytest.raises(ExternalServiceError, match="non-retryable status 401"):
        await client.fetch_page(keywords="engineer", location=None, page=1)

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_exhausting_retries_raises_external_service_error(no_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    client = _client_with_handler(handler, job_aggregator_max_retries=2)

    with pytest.raises(ExternalServiceError, match="after 3 attempt"):
        await client.fetch_page(keywords="engineer", location=None, page=1)


@pytest.mark.asyncio
async def test_connection_errors_are_retried(no_sleep):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"results": [], "count": 0})

    client = _client_with_handler(handler)
    await client.fetch_page(keywords="engineer", location=None, page=1)

    assert calls["count"] == 2
