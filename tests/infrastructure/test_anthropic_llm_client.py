"""Tests for the Anthropic implementation of LlmClientPort.

No network calls are made here — the SDK's `messages.create` is replaced
with a mock so these run offline and deterministically. See
`test_anthropic_llm_client_live.py` for opt-in real API calls, including a
live check of both model tiers.
"""

from unittest.mock import AsyncMock

import pytest
from anthropic import omit
from anthropic.types import TextBlock, Usage
from anthropic.types.message import Message
from pydantic import SecretStr

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import LlmTaskType
from src.infrastructure.config import Settings
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient

CHEAP_TASK_TYPES = [LlmTaskType.EXTRACTION, LlmTaskType.MATCHING, LlmTaskType.PARSING]
STRONG_TASK_TYPES = [LlmTaskType.RESUME_WRITING, LlmTaskType.COVER_LETTER_WRITING]


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


def _mock_create(client: AnthropicLlmClient, text: str = "pong") -> AsyncMock:
    mock = AsyncMock(return_value=_fake_response(text))
    client._client.messages.create = mock  # type: ignore[method-assign]
    return mock


def test_missing_api_key_fails_closed():
    with pytest.raises(ExternalServiceError, match="ANTHROPIC_API_KEY"):
        AnthropicLlmClient(_settings(anthropic_api_key=SecretStr("")))


@pytest.mark.asyncio
async def test_complete_returns_the_response_text():
    client = AnthropicLlmClient(_settings())
    mock_create = _mock_create(client)

    result = await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    assert result == "pong"
    mock_create.assert_awaited_once()
    _, kwargs = mock_create.await_args
    assert kwargs["messages"] == [{"role": "user", "content": "ping"}]
    assert kwargs["system"] is omit


@pytest.mark.asyncio
async def test_complete_forwards_the_system_prompt_when_given():
    client = AnthropicLlmClient(_settings())
    mock_create = _mock_create(client)

    await client.complete("ping", task_type=LlmTaskType.EXTRACTION, system="Be terse.")

    _, kwargs = mock_create.await_args
    assert kwargs["system"] == "Be terse."


@pytest.mark.asyncio
async def test_sdk_failures_are_wrapped_as_external_service_error():
    client = AnthropicLlmClient(_settings())
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("boom")
    )

    with pytest.raises(ExternalServiceError, match="Anthropic completion failed"):
        await client.complete("ping", task_type=LlmTaskType.EXTRACTION)


# ---- model routing: the point of this ticket ------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", CHEAP_TASK_TYPES)
async def test_cheap_tier_task_types_route_to_the_cheap_model(task_type):
    settings = _settings(
        anthropic_model_cheap="cheap-test-model",
        anthropic_model_strong="strong-test-model",
    )
    client = AnthropicLlmClient(settings)
    mock_create = _mock_create(client)

    await client.complete("ping", task_type=task_type)

    _, kwargs = mock_create.await_args
    assert kwargs["model"] == "cheap-test-model"


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", STRONG_TASK_TYPES)
async def test_strong_tier_task_types_route_to_the_strong_model(task_type):
    settings = _settings(
        anthropic_model_cheap="cheap-test-model",
        anthropic_model_strong="strong-test-model",
    )
    client = AnthropicLlmClient(settings)
    mock_create = _mock_create(client)

    await client.complete("ping", task_type=task_type)

    _, kwargs = mock_create.await_args
    assert kwargs["model"] == "strong-test-model"


@pytest.mark.asyncio
async def test_default_tier_models_match_the_documented_defaults():
    client = AnthropicLlmClient(_settings())
    mock_create = _mock_create(client)

    await client.complete("ping", task_type=LlmTaskType.EXTRACTION)
    _, cheap_kwargs = mock_create.await_args
    assert cheap_kwargs["model"] == "claude-haiku-4-5-20251001"

    await client.complete("ping", task_type=LlmTaskType.RESUME_WRITING)
    _, strong_kwargs = mock_create.await_args
    assert strong_kwargs["model"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_tier_model_overrides_from_config_are_respected():
    settings = _settings(
        anthropic_model_cheap="my-custom-cheap-model",
        anthropic_model_strong="my-custom-strong-model",
    )
    client = AnthropicLlmClient(settings)
    mock_create = _mock_create(client)

    await client.complete("ping", task_type=LlmTaskType.PARSING)
    assert mock_create.await_args.kwargs["model"] == "my-custom-cheap-model"

    await client.complete("ping", task_type=LlmTaskType.COVER_LETTER_WRITING)
    assert mock_create.await_args.kwargs["model"] == "my-custom-strong-model"
