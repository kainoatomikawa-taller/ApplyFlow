"""Tests for LlmJobFitRationaleGenerator — the LLM implementation of
JobFitRationaleGeneratorPort.

No network calls: `LlmClientPort` is replaced with an in-memory fake, so
these run offline and deterministically while proving the routing
contract (task_type=MATCHING -> cheap tier, enforced upstream by
`TASK_TYPE_TIERS`).
"""

from __future__ import annotations

import pytest

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.infrastructure.llm.llm_job_fit_rationale_generator import (
    LlmJobFitRationaleGenerator,
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
async def test_generate_routes_through_the_cheap_matching_task_type():
    client = FakeLlmClient("Great fit given your Python background.")
    generator = LlmJobFitRationaleGenerator(client)

    await generator.generate(
        job_title="Backend Engineer",
        company="Acme Corp",
        matched=("Python",),
        gaps=(),
    )

    assert client.calls[0][1] == LlmTaskType.MATCHING


@pytest.mark.asyncio
async def test_generate_includes_matched_and_gap_facts_in_the_prompt():
    client = FakeLlmClient("Solid match.")
    generator = LlmJobFitRationaleGenerator(client)

    await generator.generate(
        job_title="Backend Engineer",
        company="Acme Corp",
        matched=("Python", "5+ years of experience"),
        gaps=("Kubernetes",),
    )

    prompt = client.calls[0][0]
    assert "Backend Engineer" in prompt
    assert "Acme Corp" in prompt
    assert "Python" in prompt
    assert "5+ years of experience" in prompt
    assert "Kubernetes" in prompt


@pytest.mark.asyncio
async def test_generate_returns_the_stripped_rationale_text():
    client = FakeLlmClient("  A strong match for this role.  \n")
    generator = LlmJobFitRationaleGenerator(client)

    result = await generator.generate(
        job_title="Backend Engineer", company="Acme Corp", matched=(), gaps=()
    )

    assert result == "A strong match for this role."


@pytest.mark.asyncio
async def test_generate_raises_external_service_error_on_empty_response():
    client = FakeLlmClient("   ")
    generator = LlmJobFitRationaleGenerator(client)

    with pytest.raises(ExternalServiceError, match="empty response"):
        await generator.generate(
            job_title="Backend Engineer", company="Acme Corp", matched=(), gaps=()
        )


@pytest.mark.asyncio
async def test_generate_handles_no_matched_or_gap_facts():
    client = FakeLlmClient("Not enough information to say much yet.")
    generator = LlmJobFitRationaleGenerator(client)

    result = await generator.generate(
        job_title="Backend Engineer", company="Acme Corp", matched=(), gaps=()
    )

    assert result == "Not enough information to say much yet."
    prompt = client.calls[0][0]
    assert "none stated" in prompt
    assert "none" in prompt
