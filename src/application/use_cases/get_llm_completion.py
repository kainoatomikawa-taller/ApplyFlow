"""GetLlmCompletion use case.

The generic entry point for a raw LLM call. Feature-specific use cases
(resume analysis, cover-letter drafting, etc.) either depend on
`LlmClientPort` directly or compose this use case — either way, they never
reach for a provider SDK themselves.
"""

from __future__ import annotations

from src.application.dtos.llm_dtos import LlmCompletionInput, LlmCompletionOutput
from src.application.ports.llm_client_port import LlmClientPort


class GetLlmCompletion:
    def __init__(self, llm_client: LlmClientPort) -> None:
        self._llm_client = llm_client

    async def execute(self, dto: LlmCompletionInput) -> LlmCompletionOutput:
        text = await self._llm_client.complete(dto.prompt, system=dto.system)
        return LlmCompletionOutput(text=text)
