"""Tests for GreenhouseBoardClient — AtsBoardClientPort backed by
Greenhouse's public job-board API.

No network calls: `httpx.AsyncClient` is given a `MockTransport`.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from src.application.exceptions import ExternalServiceError
from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.ats_boards.greenhouse_board_client import (
    GreenhouseBoardClient,
)
from src.infrastructure.config import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"_env_file": None, "search_api_key": SecretStr("k")}
    defaults.update(overrides)
    return Settings(**defaults)


def _client_with_handler(
    handler, **settings_overrides: object
) -> GreenhouseBoardClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return GreenhouseBoardClient(
        _settings(**settings_overrides), http_client=http_client
    )


def test_provider_is_greenhouse():
    client = _client_with_handler(lambda request: httpx.Response(200, json={}))
    assert client.provider == AtsProvider.GREENHOUSE


@pytest.mark.asyncio
async def test_requests_content_true_and_finds_the_matching_job():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Frontend Engineer",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                        "content": "<p>Frontend role.</p>",
                    },
                    {
                        "title": "Backend Engineer",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
                        "content": "<p>Build <b>things</b>.</p><p>Great team.</p>",
                    },
                ]
            },
        )

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="acme", title="Backend Engineer")

    assert captured["params"]["content"] == "true"
    assert result is not None
    assert result.apply_url == "https://boards.greenhouse.io/acme/jobs/2"
    assert "Build things." in result.description
    assert "Great team." in result.description


@pytest.mark.asyncio
async def test_returns_none_when_no_job_title_matches():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Sales Manager",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                        "content": "<p>Sales role.</p>",
                    }
                ]
            },
        )

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="acme", title="Backend Engineer")

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_board_token_is_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="nonexistent", title="Engineer")

    assert result is None


@pytest.mark.asyncio
async def test_skips_jobs_missing_content_or_apply_url():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {"title": "Backend Engineer", "absolute_url": "", "content": "x"},
                    {
                        "title": "Backend Engineer",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
                        "content": "",
                    },
                ]
            },
        )

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="acme", title="Backend Engineer")

    assert result is None


@pytest.mark.asyncio
async def test_non_retryable_status_raises_external_service_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad credentials")

    client = _client_with_handler(handler)

    with pytest.raises(ExternalServiceError, match="non-retryable status 401"):
        await client.find_job(board_token="acme", title="Engineer")
