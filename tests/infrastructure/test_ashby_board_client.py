"""Tests for AshbyBoardClient — AtsBoardClientPort backed by Ashby's
public job-board posting API.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.ats_boards.ashby_board_client import AshbyBoardClient
from src.infrastructure.config import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"_env_file": None, "search_api_key": SecretStr("k")}
    defaults.update(overrides)
    return Settings(**defaults)


def _client_with_handler(handler, **settings_overrides: object) -> AshbyBoardClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return AshbyBoardClient(_settings(**settings_overrides), http_client=http_client)


def test_provider_is_ashby():
    client = _client_with_handler(
        lambda request: httpx.Response(200, json={"jobs": []})
    )
    assert client.provider == AtsProvider.ASHBY


@pytest.mark.asyncio
async def test_finds_the_matching_job_preferring_description_plain():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Frontend Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/1",
                        "descriptionPlain": "Frontend role.",
                    },
                    {
                        "title": "Backend Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/2",
                        "descriptionPlain": "Build things.",
                        "descriptionHtml": "<p>ignored html</p>",
                    },
                ]
            },
        )

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="acme", title="Backend Engineer")

    assert result is not None
    assert result.apply_url == "https://jobs.ashbyhq.com/acme/2"
    assert result.description == "Build things."


@pytest.mark.asyncio
async def test_falls_back_to_stripped_html_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Backend Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/2",
                        "descriptionHtml": "<p>Build things.</p>",
                    }
                ]
            },
        )

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="acme", title="Backend Engineer")

    assert result is not None
    assert result.description == "Build things."


@pytest.mark.asyncio
async def test_returns_none_when_no_job_matches():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Sales Manager",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/1",
                        "descriptionPlain": "Sales role.",
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
