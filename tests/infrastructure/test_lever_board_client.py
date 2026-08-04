"""Tests for LeverBoardClient — AtsBoardClientPort backed by Lever's
public postings API, which returns a bare JSON array of postings.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.ats_boards.lever_board_client import LeverBoardClient
from src.infrastructure.config import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"_env_file": None, "search_api_key": SecretStr("k")}
    defaults.update(overrides)
    return Settings(**defaults)


def _client_with_handler(handler, **settings_overrides: object) -> LeverBoardClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return LeverBoardClient(_settings(**settings_overrides), http_client=http_client)


def test_provider_is_lever():
    client = _client_with_handler(lambda request: httpx.Response(200, json=[]))
    assert client.provider == AtsProvider.LEVER


@pytest.mark.asyncio
async def test_finds_the_matching_posting_preferring_description_plain():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "text": "Frontend Engineer",
                    "hostedUrl": "https://jobs.lever.co/acme/1",
                    "descriptionPlain": "Frontend role.",
                },
                {
                    "text": "Backend Engineer",
                    "hostedUrl": "https://jobs.lever.co/acme/2",
                    "descriptionPlain": "Build things.",
                    "description": "<p>ignored html</p>",
                },
            ],
        )

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="acme", title="Backend Engineer")

    assert result is not None
    assert result.apply_url == "https://jobs.lever.co/acme/2"
    assert result.description == "Build things."


@pytest.mark.asyncio
async def test_falls_back_to_stripped_html_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "text": "Backend Engineer",
                    "hostedUrl": "https://jobs.lever.co/acme/2",
                    "description": "<p>Build things.</p>",
                }
            ],
        )

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="acme", title="Backend Engineer")

    assert result is not None
    assert result.description == "Build things."


@pytest.mark.asyncio
async def test_falls_back_to_apply_url_when_hosted_url_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "text": "Backend Engineer",
                    "applyUrl": "https://jobs.lever.co/acme/2/apply",
                    "descriptionPlain": "Build things.",
                }
            ],
        )

    client = _client_with_handler(handler)
    result = await client.find_job(board_token="acme", title="Backend Engineer")

    assert result is not None
    assert result.apply_url == "https://jobs.lever.co/acme/2/apply"


@pytest.mark.asyncio
async def test_returns_none_when_no_posting_matches():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "text": "Sales Manager",
                    "hostedUrl": "https://jobs.lever.co/acme/1",
                    "descriptionPlain": "Sales role.",
                }
            ],
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


# ---- list_jobs: the whole board ---------------------------------------------


@pytest.mark.asyncio
async def test_list_jobs_maps_levers_own_field_names():
    """Lever differs three ways: the title is `text`, the location is nested under
    `categories`, and `createdAt` is epoch milliseconds."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "text": "Backend Intern",
                    "hostedUrl": "https://jobs.lever.co/acme/1",
                    "descriptionPlain": "Write Go.",
                    "categories": {"location": "Austin, TX", "team": "Platform"},
                    "createdAt": 1782000000000,
                },
                {
                    "text": "Remote Intern",
                    "hostedUrl": "https://jobs.lever.co/acme/2",
                    "descriptionPlain": "Anywhere.",
                    "categories": {"location": "Remote"},
                    "workplaceType": "remote",
                },
            ],
        )

    postings = await _client_with_handler(handler).list_jobs(board_token="acme")

    assert [p.title for p in postings] == ["Backend Intern", "Remote Intern"]
    assert postings[0].location == "Austin, TX"
    assert postings[0].posted_at is not None
    assert postings[0].is_remote is False
    # Lever states remoteness, so it is read rather than guessed.
    assert postings[1].is_remote is True


@pytest.mark.asyncio
async def test_list_jobs_falls_back_to_apply_url_and_html_description():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "text": "Intern",
                    "applyUrl": "https://jobs.lever.co/acme/3/apply",
                    "description": "<p>Write <i>Rust</i>.</p>",
                }
            ],
        )

    postings = await _client_with_handler(handler).list_jobs(board_token="acme")

    assert postings[0].apply_url == "https://jobs.lever.co/acme/3/apply"
    assert "Rust" in postings[0].description
    assert "<i>" not in postings[0].description


@pytest.mark.asyncio
async def test_list_jobs_is_empty_when_the_board_is_not_an_array():
    postings = await _client_with_handler(
        lambda request: httpx.Response(200, json={"unexpected": "shape"})
    ).list_jobs(board_token="acme")

    assert postings == ()
