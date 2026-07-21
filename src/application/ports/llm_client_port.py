"""LlmClientPort — the single outbound abstraction for LLM access.

Every feature that needs a completion from a large language model depends
on this port, never on a provider SDK directly. The infrastructure layer
implements it once (see `AnthropicLlmClient`); use cases stay ignorant of
which model or provider answers the call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LlmClientPort(ABC):
    """Sends a prompt to an LLM and returns its text completion."""

    @abstractmethod
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Return the model's text completion for `prompt`.

        `system` optionally sets the system prompt. Raises
        `src.application.exceptions.ExternalServiceError` if the call fails.
        """
