"""EmbeddingClientPort — the outbound abstraction for text-embedding
generation.

Sits alongside `LlmClientPort` as part of the Epic 00 LLM layer: every
feature that needs a vector embedding depends on this port, never on a
provider SDK directly. The infrastructure layer implements it once (see
`OpenAiEmbeddingClient`); use cases stay ignorant of which model or
provider answers the call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingClientPort(ABC):
    """Turns text into a vector embedding."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return a vector embedding for `text`.

        Raises `src.application.exceptions.ExternalServiceError` if the
        call fails.
        """
