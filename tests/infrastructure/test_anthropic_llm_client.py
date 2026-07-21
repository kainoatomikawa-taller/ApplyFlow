"""Tests for the Anthropic implementation of LlmClientPort.

No network calls are made here — the SDK's `messages.create` is replaced
with a mock so these run offline and deterministically. See
`test_anthropic_llm_client_live.py` for opt-in real API calls, including a
live check of both model tiers.
"""

from unittest.mock import AsyncMock

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RequestTooLargeError,
    UnprocessableEntityError,
    omit,
)
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


def _fake_response(text: str, usage: Usage | None = None) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-haiku-4-5-20251001",
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=usage if usage is not None else Usage(input_tokens=1, output_tokens=1),
    )


def _mock_create(
    client: AnthropicLlmClient, text: str = "pong", usage: Usage | None = None
) -> AsyncMock:
    mock = AsyncMock(return_value=_fake_response(text, usage))
    client._client.messages.create = mock  # type: ignore[method-assign]
    return mock


_FAKE_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls: type[APIStatusError], status_code: int) -> APIStatusError:
    response = httpx.Response(status_code, request=_FAKE_REQUEST)
    return cls(f"boom ({status_code})", response=response, body=None)


def _connection_error() -> APIConnectionError:
    return APIConnectionError(request=_FAKE_REQUEST)


@pytest.fixture
def no_sleep(monkeypatch):
    """Patch out `asyncio.sleep` so retry-backoff tests don't wait for real."""
    mock = AsyncMock()
    monkeypatch.setattr("src.infrastructure.llm.anthropic_client.asyncio.sleep", mock)
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
    assert kwargs["system"] == [
        {
            "type": "text",
            "text": "Be terse.",
            "cache_control": {"type": "ephemeral"},
        }
    ]


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


# ---- prompt caching: the point of this ticket -----------------------------


@pytest.mark.asyncio
async def test_no_system_prompt_is_still_omitted_not_cached():
    client = AnthropicLlmClient(_settings())
    mock_create = _mock_create(client)

    await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    assert mock_create.await_args.kwargs["system"] is omit


@pytest.mark.asyncio
async def test_system_prompt_is_marked_with_an_ephemeral_cache_breakpoint():
    client = AnthropicLlmClient(_settings())
    mock_create = _mock_create(client)

    await client.complete("ping", task_type=LlmTaskType.EXTRACTION, system="Be terse.")

    system_param = mock_create.await_args.kwargs["system"]
    assert system_param == [
        {
            "type": "text",
            "text": "Be terse.",
            "cache_control": {"type": "ephemeral"},
        }
    ]


@pytest.mark.asyncio
async def test_caching_does_not_alter_the_returned_completion_text():
    client = AnthropicLlmClient(_settings())
    _mock_create(
        client,
        text="the actual answer",
        usage=Usage(
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=0,
        ),
    )

    result = await client.complete(
        "ping", task_type=LlmTaskType.EXTRACTION, system="Be terse."
    )

    assert result == "the actual answer"


@pytest.mark.asyncio
async def test_cache_read_is_logged_as_a_hit(caplog):
    client = AnthropicLlmClient(_settings())
    _mock_create(
        client,
        usage=Usage(
            input_tokens=5,
            output_tokens=1,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=0,
        ),
    )

    with caplog.at_level("INFO", logger="src.infrastructure.llm.anthropic_client"):
        await client.complete(
            "ping", task_type=LlmTaskType.EXTRACTION, system="Be terse."
        )

    assert any(
        "cache hit" in record.message
        and "cache_read_input_tokens=500" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_cache_creation_is_logged_on_first_call(caplog):
    client = AnthropicLlmClient(_settings())
    _mock_create(
        client,
        usage=Usage(
            input_tokens=5,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=500,
        ),
    )

    with caplog.at_level("INFO", logger="src.infrastructure.llm.anthropic_client"):
        await client.complete(
            "ping", task_type=LlmTaskType.EXTRACTION, system="Be terse."
        )

    assert any(
        "cache_creation_input_tokens=500" in record.message for record in caplog.records
    )


@pytest.mark.asyncio
async def test_no_cache_activity_logs_nothing(caplog):
    client = AnthropicLlmClient(_settings())
    _mock_create(client)

    with caplog.at_level("INFO", logger="src.infrastructure.llm.anthropic_client"):
        await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    assert not caplog.records


# ---- retry/backoff: the point of this ticket -------------------------------


def _fails_then_succeeds(*exceptions: Exception, text: str = "pong") -> AsyncMock:
    return AsyncMock(side_effect=[*exceptions, _fake_response(text)])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        RateLimitError,
        InternalServerError,
    ],
)
async def test_retries_on_transient_status_errors_and_then_succeeds(exc, no_sleep):
    status_code = 429 if exc is RateLimitError else 503
    client = AnthropicLlmClient(_settings())
    client._client.messages.create = _fails_then_succeeds(  # type: ignore[method-assign]
        _status_error(exc, status_code)
    )

    result = await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    assert result == "pong"
    assert client._client.messages.create.await_count == 2
    no_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_retries_on_connection_errors(no_sleep):
    client = AnthropicLlmClient(_settings())
    client._client.messages.create = _fails_then_succeeds(  # type: ignore[method-assign]
        _connection_error()
    )

    result = await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    assert result == "pong"
    assert client._client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_retries_on_lock_timeout_409(no_sleep):
    from anthropic import ConflictError

    client = AnthropicLlmClient(_settings())
    client._client.messages.create = _fails_then_succeeds(  # type: ignore[method-assign]
        _status_error(ConflictError, 409)
    )

    result = await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    assert result == "pong"


@pytest.mark.asyncio
async def test_backoff_delay_doubles_and_is_capped():
    client = AnthropicLlmClient(
        _settings(
            anthropic_retry_base_delay_seconds=1.0,
            anthropic_retry_max_delay_seconds=5.0,
        )
    )

    assert client._backoff_delay(1) == 1.0
    assert client._backoff_delay(2) == 2.0
    assert client._backoff_delay(3) == 4.0
    assert client._backoff_delay(4) == 5.0  # capped
    assert client._backoff_delay(10) == 5.0  # still capped


@pytest.mark.asyncio
async def test_exhausting_retries_on_a_persistent_transient_error_raises(no_sleep):
    client = AnthropicLlmClient(_settings(anthropic_max_retries=2))
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        side_effect=_status_error(RateLimitError, 429)
    )

    with pytest.raises(ExternalServiceError, match="after 3 attempt"):
        await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    assert client._client.messages.create.await_count == 3


@pytest.mark.asyncio
async def test_max_retries_is_configurable(no_sleep):
    client = AnthropicLlmClient(_settings(anthropic_max_retries=0))
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        side_effect=_status_error(RateLimitError, 429)
    )

    with pytest.raises(ExternalServiceError, match="after 1 attempt"):
        await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    assert client._client.messages.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc,match",
    [
        (AuthenticationError, "ANTHROPIC_API_KEY"),
        (PermissionDeniedError, "denied permission"),
        (NotFoundError, "could not find"),
        (RequestTooLargeError, "too large"),
        (BadRequestError, "invalid"),
        (UnprocessableEntityError, "invalid"),
    ],
)
async def test_non_retryable_status_errors_surface_immediately_with_a_clear_message(
    exc, match
):
    status_codes = {
        AuthenticationError: 401,
        PermissionDeniedError: 403,
        NotFoundError: 404,
        RequestTooLargeError: 413,
        BadRequestError: 400,
        UnprocessableEntityError: 422,
    }
    client = AnthropicLlmClient(_settings())
    mock_create = AsyncMock(side_effect=_status_error(exc, status_codes[exc]))
    client._client.messages.create = mock_create  # type: ignore[method-assign]

    with pytest.raises(ExternalServiceError, match=match):
        await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    mock_create.assert_awaited_once()  # no retry on a non-retryable error


@pytest.mark.asyncio
async def test_unexpected_non_anthropic_errors_are_not_retried():
    client = AnthropicLlmClient(_settings())
    mock_create = AsyncMock(side_effect=RuntimeError("boom"))
    client._client.messages.create = mock_create  # type: ignore[method-assign]

    with pytest.raises(ExternalServiceError, match="Anthropic completion failed"):
        await client.complete("ping", task_type=LlmTaskType.EXTRACTION)

    mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_sdk_internal_retries_are_disabled_in_favor_of_our_own():
    client = AnthropicLlmClient(_settings())

    assert client._client.max_retries == 0
