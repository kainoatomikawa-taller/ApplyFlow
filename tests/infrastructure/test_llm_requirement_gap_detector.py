"""Tests for LlmRequirementGapDetector — the LLM implementation of
RequirementGapDetectorPort.

No network calls: `LlmClientPort` is replaced with an in-memory fake, so
these run offline and deterministically while proving both the routing
contract (task_type=MATCHING -> cheap tier) and the anti-fabrication
guard (only lines that exactly match a given requirement ever come back).
"""

from __future__ import annotations

import pytest

from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.infrastructure.llm.llm_requirement_gap_detector import (
    LlmRequirementGapDetector,
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
async def test_detect_gaps_routes_through_the_cheap_matching_task_type():
    client = FakeLlmClient("NONE")
    detector = LlmRequirementGapDetector(client)

    await detector.detect_gaps(
        job_title="Backend Engineer",
        company="Acme Corp",
        requirements=("Python",),
        candidate_facts=("Skill: Python",),
    )

    assert client.calls[0][1] == LlmTaskType.MATCHING


@pytest.mark.asyncio
async def test_detect_gaps_includes_requirements_and_facts_in_the_prompt():
    client = FakeLlmClient("NONE")
    detector = LlmRequirementGapDetector(client)

    await detector.detect_gaps(
        job_title="Backend Engineer",
        company="Acme Corp",
        requirements=("Kubernetes",),
        candidate_facts=("Skill: Python",),
    )

    prompt = client.calls[0][0]
    assert "Backend Engineer" in prompt
    assert "Acme Corp" in prompt
    assert "Kubernetes" in prompt
    assert "Skill: Python" in prompt


@pytest.mark.asyncio
async def test_detect_gaps_returns_requirements_the_model_flags():
    client = FakeLlmClient("Kubernetes\n5+ years of experience")
    detector = LlmRequirementGapDetector(client)

    gaps = await detector.detect_gaps(
        job_title="Backend Engineer",
        company="Acme Corp",
        requirements=("Python", "Kubernetes", "5+ years of experience"),
        candidate_facts=("Skill: Python",),
    )

    assert gaps == ("Kubernetes", "5+ years of experience")


@pytest.mark.asyncio
async def test_detect_gaps_none_response_yields_no_gaps():
    client = FakeLlmClient("NONE")
    detector = LlmRequirementGapDetector(client)

    gaps = await detector.detect_gaps(
        job_title="Backend Engineer",
        company="Acme Corp",
        requirements=("Python",),
        candidate_facts=("Skill: Python",),
    )

    assert gaps == ()


@pytest.mark.asyncio
async def test_detect_gaps_drops_hallucinated_lines_not_in_requirements():
    client = FakeLlmClient("Kubernetes\nA PhD in astrophysics")
    detector = LlmRequirementGapDetector(client)

    gaps = await detector.detect_gaps(
        job_title="Backend Engineer",
        company="Acme Corp",
        requirements=("Python", "Kubernetes"),
        candidate_facts=("Skill: Python",),
    )

    assert gaps == ("Kubernetes",)


@pytest.mark.asyncio
async def test_detect_gaps_short_circuits_on_empty_requirements():
    client = FakeLlmClient("NONE")
    detector = LlmRequirementGapDetector(client)

    gaps = await detector.detect_gaps(
        job_title="Backend Engineer",
        company="Acme Corp",
        requirements=(),
        candidate_facts=("Skill: Python",),
    )

    assert gaps == ()
    assert client.calls == []
