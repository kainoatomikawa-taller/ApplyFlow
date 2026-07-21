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
"""

from __future__ import annotations

import logging

from anthropic import AsyncAnthropic, Omit, omit
from anthropic.types import TextBlock, TextBlockParam, Usage

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import (
    TASK_TYPE_TIERS,
    LlmClientPort,
    LlmModelTier,
    LlmTaskType,
)
from src.infrastructure.config import Settings

logger = logging.getLogger(__name__)


class AnthropicLlmClient(LlmClientPort):
    def __init__(self, settings: Settings) -> None:
        api_key = settings.anthropic_api_key.get_secret_value()
        if not api_key:
            raise ExternalServiceError(
                "ANTHROPIC_API_KEY is not configured; cannot authenticate to Anthropic."
            )
        self._client = AsyncAnthropic(api_key=api_key)
        self._models: dict[LlmModelTier, str] = {
            LlmModelTier.CHEAP: settings.anthropic_model_cheap,
            LlmModelTier.STRONG: settings.anthropic_model_strong,
        }
        self._max_tokens = settings.anthropic_max_tokens

    async def complete(
        self, prompt: str, *, task_type: LlmTaskType, system: str | None = None
    ) -> str:
        model = self._models[TASK_TYPE_TIERS[task_type]]
        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
                system=self._to_system_param(system),
            )
        except Exception as exc:  # noqa: BLE001 - re-thrown as app-level error
            raise ExternalServiceError(f"Anthropic completion failed: {exc}") from exc

        self._log_cache_usage(response.usage)

        return "".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        )

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
