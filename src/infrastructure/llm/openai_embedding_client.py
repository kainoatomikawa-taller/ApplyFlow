"""OpenAI implementation of the EmbeddingClientPort.

Anthropic (the provider behind `AnthropicLlmClient`, the rest of the Epic
00 LLM layer) has no embeddings endpoint, so this is the one place in that
layer that talks to a different provider — the `openai` SDK, used
directly and only here, the same way `AnthropicLlmClient` is the only
place that imports `anthropic`. Authentication reuses the existing
`OPENAI_API_KEY` (`Settings.openai_api_key`); the model id is a config
override point (`Settings.openai_embedding_model`), so callers never pick
a model, only ask for an embedding.
"""

from __future__ import annotations

from openai import AsyncOpenAI, OpenAIError

from src.application.exceptions import ExternalServiceError
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.infrastructure.config import Settings


class OpenAiEmbeddingClient(EmbeddingClientPort):
    def __init__(self, settings: Settings) -> None:
        api_key = settings.openai_api_key.get_secret_value()
        if not api_key:
            raise ExternalServiceError(
                "OPENAI_API_KEY is not configured; cannot authenticate to "
                "OpenAI for embeddings."
            )
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = settings.openai_embedding_model

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self._client.embeddings.create(
                model=self._model, input=text
            )
        except OpenAIError as exc:
            raise ExternalServiceError(
                f"OpenAI embedding request failed: {exc}"
            ) from exc
        return list(response.data[0].embedding)
