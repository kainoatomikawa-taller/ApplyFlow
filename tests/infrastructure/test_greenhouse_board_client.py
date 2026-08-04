"""Tests for GreenhouseBoardClient — AtsBoardClientPort backed by
Greenhouse's public job-board API.

No network calls: `httpx.AsyncClient` is given a `MockTransport`.
"""

from __future__ import annotations

from datetime import date
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


# ---- list_jobs: the whole board ---------------------------------------------
#
# Added with the direct-board ingest. `find_job` now reads this same mapping via
# `BoardClientBase`, so these also cover the fields that path relies on.


@pytest.mark.asyncio
async def test_list_jobs_maps_the_whole_board():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Backend Intern",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                        "content": "<p>Write <b>Python</b>.</p>",
                        "location": {"name": "Austin, TX"},
                        "first_published": "2026-07-01T12:00:00-05:00",
                    },
                    {
                        "title": "Data Intern",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
                        "content": "<p>Write SQL.</p>",
                        "location": {"name": "Remote"},
                        "updated_at": "2026-06-15T09:30:00Z",
                    },
                ]
            },
        )

    postings = await _client_with_handler(handler).list_jobs(board_token="acme")

    assert [p.title for p in postings] == ["Backend Intern", "Data Intern"]
    # HTML is flattened to text, as the description column expects.
    assert "Python" in postings[0].description
    assert "<b>" not in postings[0].description
    assert postings[0].location == "Austin, TX"
    assert postings[0].posted_at == date(2026, 7, 1)
    # Falls back to updated_at when first_published is absent.
    assert postings[1].posted_at == date(2026, 6, 15)


@pytest.mark.asyncio
async def test_list_jobs_drops_entries_missing_a_required_field():
    """A JobPosting cannot exist without a title, an apply URL and a description,
    so a half-published board entry is omitted rather than surfaced broken."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {"title": "No URL", "content": "<p>x</p>"},
                    {"absolute_url": "https://x.example.com", "content": "<p>x</p>"},
                    {"title": "No content", "absolute_url": "https://y.example.com"},
                    {
                        "title": "Complete",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/9",
                        "content": "<p>Real description.</p>",
                    },
                    "not even an object",
                ]
            },
        )

    postings = await _client_with_handler(handler).list_jobs(board_token="acme")

    assert [p.title for p in postings] == ["Complete"]


@pytest.mark.asyncio
async def test_list_jobs_never_guesses_remote_for_greenhouse():
    """Greenhouse publishes no remote flag. "Remote" in the location text is not
    the same as the company stating it, so nothing is inferred."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "title": "Intern",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                        "content": "<p>x</p>",
                        "location": {"name": "Remote"},
                    }
                ]
            },
        )

    postings = await _client_with_handler(handler).list_jobs(board_token="acme")

    assert postings[0].is_remote is False
    assert postings[0].location == "Remote"


@pytest.mark.asyncio
async def test_list_jobs_is_empty_for_a_board_that_does_not_exist():
    """Greenhouse answers 404 for an unknown token, which `get_json_or_none`
    already treats as a routine outcome."""
    postings = await _client_with_handler(
        lambda request: httpx.Response(404, text="not found")
    ).list_jobs(board_token="nope")

    assert postings == ()
