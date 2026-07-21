"""Tests for the Anthropic implementation of LlmClientPort.

No network calls are made here — the SDK's `messages.create` is replaced
with a mock so these run offline and deterministically. See
`test_anthropic_llm_client_live.py` for an opt-in real API call.
"""

from unittest.mock import AsyncMock

import pytest
from anthropic import omit
from anthropic.types import TextBlock, Usage
from anthropic.types.message import Message
from pydantic import SecretStr

from src.application.exceptions import ExternalServiceError
from src.infrastructure.config import Settings
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "anthropic_api_key": SecretStr("sk-ant-test-key"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _fake_response(text: str) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-haiku-4-5-20251001",
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def test_missing_api_key_fails_closed():
    with pytest.raises(ExternalServiceError, match="ANTHROPIC_API_KEY"):
        AnthropicLlmClient(_settings(anthropic_api_key=SecretStr("")))


@pytest.mark.asyncio
async def test_complete_returns_the_response_text():
    client = AnthropicLlmClient(_settings())
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_fake_response("pong")
    )

    result = await client.complete("ping")

    assert result == "pong"
    client._client.messages.create.assert_awaited_once()
    _, kwargs = client._client.messages.create.await_args
    assert kwargs["messages"] == [{"role": "user", "content": "ping"}]
    assert kwargs["system"] is omit


@pytest.mark.asyncio
async def test_complete_forwards_the_system_prompt_when_given():
    client = AnthropicLlmClient(_settings())
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_fake_response("pong")
    )

    await client.complete("ping", system="You are terse.")

    _, kwargs = client._client.messages.create.await_args
    assert kwargs["system"] == "You are terse."


@pytest.mark.asyncio
async def test_sdk_failures_are_wrapped_as_external_service_error():
    client = AnthropicLlmClient(_settings())
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("boom")
    )

    with pytest.raises(ExternalServiceError, match="Anthropic completion failed"):
        await client.complete("ping")
