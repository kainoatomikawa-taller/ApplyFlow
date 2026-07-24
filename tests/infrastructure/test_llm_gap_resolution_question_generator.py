"""Tests for LlmGapResolutionQuestionGenerator — the LLM implementation of
GapResolutionQuestionGeneratorPort.

No network calls: `LlmClientPort` is replaced with an in-memory fake, so
these run offline and deterministically while proving the routing
contract (task_type=MATCHING -> cheap tier, enforced upstream by
`TASK_TYPE_TIERS`).
"""

from __future__ import annotations

import pytest

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.infrastructure.llm.llm_gap_resolution_question_generator import (
    LlmGapResolutionQuestionGenerator,
)


class FakeLlmClient(LlmClientPort):
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, LlmTaskType, str | None]] = []

    async def complete(
        self, prompt: str, *, task_type: LlmTaskType, system: str | None = None
    ) -> str:
        self.calls.append((prompt, task_type, system))
        return self.response


@pytest.mark.asyncio
async def test_generate_question_routes_through_the_cheap_matching_task_type():
    client = FakeLlmClient("Have you ever led a team or run a project?")
    generator = LlmGapResolutionQuestionGenerator(client)

    await generator.generate_question(gap="Leadership experience preferred")

    assert client.calls[0][1] == LlmTaskType.MATCHING


@pytest.mark.asyncio
async def test_generate_question_includes_the_gap_in_the_prompt():
    client = FakeLlmClient("Have you worked with Kubernetes?")
    generator = LlmGapResolutionQuestionGenerator(client)

    await generator.generate_question(gap="Kubernetes")

    prompt = client.calls[0][0]
    assert "Kubernetes" in prompt


@pytest.mark.asyncio
async def test_generate_question_returns_the_stripped_question_text():
    client = FakeLlmClient("  Have you led a team before?  \n")
    generator = LlmGapResolutionQuestionGenerator(client)

    result = await generator.generate_question(gap="Leadership experience")

    assert result == "Have you led a team before?"


@pytest.mark.asyncio
async def test_generate_question_raises_external_service_error_on_empty_response():
    client = FakeLlmClient("   ")
    generator = LlmGapResolutionQuestionGenerator(client)

    with pytest.raises(ExternalServiceError, match="empty response"):
        await generator.generate_question(gap="Kubernetes")


@pytest.mark.asyncio
async def test_generate_question_system_prompt_instructs_neutrality():
    client = FakeLlmClient("Have you led a team before?")
    generator = LlmGapResolutionQuestionGenerator(client)

    await generator.generate_question(gap="Leadership experience")

    system_prompt = client.calls[0][2]
    assert system_prompt is not None
    assert "neutral" in system_prompt.lower()
    assert "never imply" in system_prompt.lower()
