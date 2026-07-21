"""Anthropic implementation of the LlmClientPort.

This is the ONLY place in the codebase that imports the Anthropic SDK.
Every LLM-backed feature depends on `LlmClientPort` and receives this
adapter through a composition root — never instantiate `anthropic.*`
directly anywhere else.

Authentication is a pay-as-you-go Anthropic API key, passed explicitly as
`api_key=`. Subscription/claude.ai login credentials (OAuth session
tokens, the `claude` CLI's stored credentials, etc.) are never read or
accepted here — there is no code path in this class that looks for them.

Model routing: this class's only job re: model selection is turning the
`LlmModelTier` that `TASK_TYPE_TIERS` picked for a call's `LlmTaskType`
into a concrete model id, sourced from config (`ANTHROPIC_MODEL_CHEAP` /
`ANTHROPIC_MODEL_STRONG`). Callers never see a tier or a model — only a
task type.

Prompt caching: when a caller supplies `system`, it is assumed to be a
stable, reusable prompt (instructions that don't change between calls)
and is marked with an ephemeral `cache_control` breakpoint so Anthropic
caches it server-side. This is the only place that decision is made, so
every use case gets the discount on repeat calls without doing anything
special.

Retries: the SDK's own built-in retry (`max_retries=`) is turned off in
favor of the loop in `_create_with_retry` below, so this class is the
single source of truth for retry/backoff policy — configurable via
`ANTHROPIC_MAX_RETRIES` / `ANTHROPIC_RETRY_BASE_DELAY_SECONDS` /
`ANTHROPIC_RETRY_MAX_DELAY_SECONDS` — instead of two overlapping retry
loops with independent backoff schedules. Only transient errors (rate
limits, request/lock timeouts, 5xxs, connection failures) are retried;
everything else (bad request, auth, not found, payload too large, ...)
surfaces immediately as an `ExternalServiceError` with a message naming
what actually went wrong, since retrying those would never succeed.
"""

from __future__ import annotations

import asyncio
import logging

from anthropic import (
    AnthropicError,
    APIConnectionError,
    APIStatusError,
    AsyncAnthropic,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    Omit,
    PermissionDeniedError,
    RequestTooLargeError,
    UnprocessableEntityError,
    omit,
)
from anthropic.types import Message, TextBlock, TextBlockParam, Usage

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import (
    TASK_TYPE_TIERS,
    LlmClientPort,
    LlmModelTier,
    LlmTaskType,
)
from src.infrastructure.config import Settings

logger = logging.getLogger(__name__)

#: HTTP status codes worth retrying that don't already fall out of
#: `status_code >= 500` (request timeout, lock/concurrency timeout, rate
#: limit) — mirrors the semantics of the SDK's own (now-disabled) retry
#: policy, just under our own configurable backoff.
_RETRYABLE_STATUS_CODES = {408, 409, 429}


class AnthropicLlmClient(LlmClientPort):
    def __init__(self, settings: Settings) -> None:
        api_key = settings.anthropic_api_key.get_secret_value()
        if not api_key:
            raise ExternalServiceError(
                "ANTHROPIC_API_KEY is not configured; cannot authenticate to Anthropic."
            )
        # max_retries=0: this class owns retry/backoff (see module docstring).
        self._client = AsyncAnthropic(api_key=api_key, max_retries=0)
        self._models: dict[LlmModelTier, str] = {
            LlmModelTier.CHEAP: settings.anthropic_model_cheap,
            LlmModelTier.STRONG: settings.anthropic_model_strong,
        }
        self._max_tokens = settings.anthropic_max_tokens
        self._max_retries = settings.anthropic_max_retries
        self._retry_base_delay = settings.anthropic_retry_base_delay_seconds
        self._retry_max_delay = settings.anthropic_retry_max_delay_seconds

    async def complete(
        self, prompt: str, *, task_type: LlmTaskType, system: str | None = None
    ) -> str:
        model = self._models[TASK_TYPE_TIERS[task_type]]
        response = await self._create_with_retry(
            model=model, prompt=prompt, system=system
        )

        self._log_cache_usage(response.usage)

        return "".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        )

    async def _create_with_retry(
        self, *, model: str, prompt: str, system: str | None
    ) -> Message:
        max_attempts = self._max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return await self._client.messages.create(
                    model=model,
                    max_tokens=self._max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                    system=self._to_system_param(system),
                )
            except Exception as exc:  # noqa: BLE001 - classified below
                if not isinstance(exc, AnthropicError):
                    raise ExternalServiceError(
                        f"Anthropic completion failed: {exc}"
                    ) from exc
                if not self._is_retryable(exc):
                    raise ExternalServiceError(
                        self._non_retryable_message(exc)
                    ) from exc

                last_exc = exc
                if attempt == max_attempts:
                    break
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "anthropic request failed with %s (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    type(exc).__name__,
                    attempt,
                    max_attempts,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        raise ExternalServiceError(
            f"Anthropic request failed after {max_attempts} attempt(s) due to a "
            f"transient error ({type(last_exc).__name__}): {last_exc}"
        ) from last_exc

    def _backoff_delay(self, attempt: int) -> float:
        delay = self._retry_base_delay * (2 ** (attempt - 1))
        return float(min(delay, self._retry_max_delay))

    @staticmethod
    def _is_retryable(exc: AnthropicError) -> bool:
        if isinstance(exc, APIConnectionError):
            return True
        if isinstance(exc, APIStatusError):
            return exc.status_code in _RETRYABLE_STATUS_CODES or exc.status_code >= 500
        return False

    @staticmethod
    def _non_retryable_message(exc: AnthropicError) -> str:
        if isinstance(exc, AuthenticationError):
            return (
                "Anthropic rejected the API key (401 authentication error) — "
                f"check ANTHROPIC_API_KEY is a valid pay-as-you-go key: {exc}"
            )
        if isinstance(exc, PermissionDeniedError):
            return f"Anthropic denied permission for this request (403): {exc}"
        if isinstance(exc, NotFoundError):
            return (
                f"Anthropic could not find the requested model or resource (404): {exc}"
            )
        if isinstance(exc, RequestTooLargeError):
            return f"Anthropic rejected the request as too large (413): {exc}"
        if isinstance(exc, (BadRequestError, UnprocessableEntityError)):
            return (
                f"Anthropic rejected the request as invalid, retrying won't help: {exc}"
            )
        if isinstance(exc, APIStatusError):
            return (
                f"Anthropic request failed with non-retryable status "
                f"{exc.status_code}: {exc}"
            )
        return f"Anthropic completion failed with a non-retryable error: {exc}"

    @staticmethod
    def _to_system_param(system: str | None) -> list[TextBlockParam] | Omit:
        """Turn a plain system string into a cache-eligible block.

        A single `cache_control: ephemeral` breakpoint at the end of the
        system prompt tells Anthropic to cache everything up to that
        point, so callers that pass the same stable `system` string on
        every call get it served from cache instead of re-processed.
        """
        if system is None:
            return omit
        return [
            TextBlockParam(
                type="text",
                text=system,
                cache_control={"type": "ephemeral"},
            )
        ]

    @staticmethod
    def _log_cache_usage(usage: Usage) -> None:
        cache_read = usage.cache_read_input_tokens or 0
        cache_created = usage.cache_creation_input_tokens or 0
        if cache_read or cache_created:
            logger.info(
                "anthropic prompt cache %s: cache_read_input_tokens=%d "
                "cache_creation_input_tokens=%d input_tokens=%d",
                "hit" if cache_read else "miss (populated)",
                cache_read,
                cache_created,
                usage.input_tokens,
            )
