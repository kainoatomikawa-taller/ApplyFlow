"""Tests for OpenAiEmbeddingClient — the implementation of EmbeddingClientPort.

No network calls: `AsyncOpenAI.embeddings.create` is replaced with a mock
so these run offline and deterministically.
"""

from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, AuthenticationError
from pydantic import SecretStr

from src.application.exceptions import ExternalServiceError
from src.infrastructure.config import Settings
from src.infrastructure.llm.openai_embedding_client import OpenAiEmbeddingClient

_FAKE_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/embeddings")


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "openai_api_key": SecretStr("sk-test-key"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


class _FakeEmbeddingData:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, embedding: list[float]) -> None:
        self.data = [_FakeEmbeddingData(embedding)]


def test_missing_api_key_fails_closed():
    with pytest.raises(ExternalServiceError, match="OPENAI_API_KEY"):
        OpenAiEmbeddingClient(_settings(openai_api_key=SecretStr("")))


@pytest.mark.asyncio
async def test_embed_returns_the_response_vector():
    client = OpenAiEmbeddingClient(_settings())
    mock_create = AsyncMock(return_value=_FakeEmbeddingResponse([0.1, 0.2, 0.3]))
    client._client.embeddings.create = mock_create  # type: ignore[method-assign]

    result = await client.embed("Are you willing to relocate?")

    assert result == [0.1, 0.2, 0.3]
    mock_create.assert_awaited_once()
    _, kwargs = mock_create.await_args
    assert kwargs["input"] == "Are you willing to relocate?"


@pytest.mark.asyncio
async def test_embed_uses_the_configured_model():
    client = OpenAiEmbeddingClient(_settings(openai_embedding_model="my-embed-model"))
    mock_create = AsyncMock(return_value=_FakeEmbeddingResponse([0.1]))
    client._client.embeddings.create = mock_create  # type: ignore[method-assign]

    await client.embed("some question")

    assert mock_create.await_args.kwargs["model"] == "my-embed-model"


@pytest.mark.asyncio
async def test_default_embedding_model_matches_the_documented_default():
    client = OpenAiEmbeddingClient(_settings())
    mock_create = AsyncMock(return_value=_FakeEmbeddingResponse([0.1]))
    client._client.embeddings.create = mock_create  # type: ignore[method-assign]

    await client.embed("some question")

    assert mock_create.await_args.kwargs["model"] == "text-embedding-3-small"


@pytest.mark.asyncio
async def test_sdk_failures_are_wrapped_as_external_service_error():
    client = OpenAiEmbeddingClient(_settings())
    client._client.embeddings.create = AsyncMock(  # type: ignore[method-assign]
        side_effect=APIConnectionError(request=_FAKE_REQUEST)
    )

    with pytest.raises(ExternalServiceError, match="OpenAI embedding request failed"):
        await client.embed("some question")


@pytest.mark.asyncio
async def test_authentication_errors_are_wrapped_as_external_service_error():
    response = httpx.Response(401, request=_FAKE_REQUEST)
    client = OpenAiEmbeddingClient(_settings())
    client._client.embeddings.create = AsyncMock(  # type: ignore[method-assign]
        side_effect=AuthenticationError("bad key", response=response, body=None)
    )

    with pytest.raises(ExternalServiceError, match="OpenAI embedding request failed"):
        await client.embed("some question")
