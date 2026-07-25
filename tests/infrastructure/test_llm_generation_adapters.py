"""Tests for LlmTailoredResumeGenerator and LlmCoverLetterGenerator — the
LLM implementations of the two generation ports.

No network calls: `LlmClientPort` is replaced with an in-memory fake, so
these run offline while proving the routing contract (RESUME_WRITING and
COVER_LETTER_WRITING -> strong tier, enforced upstream by
`TASK_TYPE_TIERS`) and that the prompt carries the candidate's facts and
keeps requirements labeled as something other than facts.
"""

from __future__ import annotations

import pytest

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.infrastructure.llm.llm_cover_letter_generator import LlmCoverLetterGenerator
from src.infrastructure.llm.llm_tailored_resume_generator import (
    LlmTailoredResumeGenerator,
)

_FACTS = ("Skill: Python", "Worked as Backend Engineer at Acme Corp")
_REQUIREMENTS = ("Python", "Terraform")


class FakeLlmClient(LlmClientPort):
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, LlmTaskType, str | None]] = []

    async def complete(
        self, prompt: str, *, task_type: LlmTaskType, system: str | None = None
    ) -> str:
        self.calls.append((prompt, task_type, system))
        return self.response


def _generators(client: FakeLlmClient):
    return (
        LlmTailoredResumeGenerator(client),
        LlmCoverLetterGenerator(client),
    )


async def _generate(generator) -> str:
    return await generator.generate(
        job_title="Senior Platform Engineer",
        company="Globex",
        requirements=_REQUIREMENTS,
        facts=_FACTS,
    )


@pytest.mark.asyncio
async def test_resume_generation_routes_through_the_resume_writing_task_type():
    client = FakeLlmClient("EXPERIENCE\nBackend Engineer at Acme Corp")

    await _generate(LlmTailoredResumeGenerator(client))

    assert client.calls[0][1] == LlmTaskType.RESUME_WRITING


@pytest.mark.asyncio
async def test_cover_letter_generation_routes_through_its_own_task_type():
    client = FakeLlmClient("Dear Hiring Manager,")

    await _generate(LlmCoverLetterGenerator(client))

    assert client.calls[0][1] == LlmTaskType.COVER_LETTER_WRITING


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1])
async def test_the_prompt_carries_the_facts_and_the_job(index: int):
    client = FakeLlmClient("draft")

    await _generate(_generators(client)[index])

    prompt = client.calls[0][0]
    assert "Senior Platform Engineer" in prompt
    assert "Globex" in prompt
    for fact in _FACTS:
        assert fact in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1])
async def test_requirements_are_labeled_as_not_being_facts(index: int):
    """The prompt has to keep the two lists apart, or the model will read
    the job's wish list as the candidate's history."""
    client = FakeLlmClient("draft")

    await _generate(_generators(client)[index])

    prompt = client.calls[0][0]
    assert "Terraform" in prompt
    assert "not facts about the candidate" in prompt.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1])
async def test_the_system_prompt_forbids_inventing_material(index: int):
    client = FakeLlmClient("draft")

    await _generate(_generators(client)[index])

    system = client.calls[0][2] or ""
    assert "the facts do not say" in system
    assert "never round, scale" in system.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1])
async def test_an_empty_fact_list_is_still_sent_rather_than_faked(index: int):
    client = FakeLlmClient("draft")

    await _generators(client)[index].generate(
        job_title="Senior Platform Engineer",
        company="Globex",
        requirements=(),
        facts=(),
    )

    prompt = client.calls[0][0]
    assert "none on file" in prompt
    assert "none stated" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1])
async def test_surrounding_whitespace_is_trimmed_from_the_draft(index: int):
    client = FakeLlmClient("\n  Dear Hiring Manager,  \n")

    result = await _generate(_generators(client)[index])

    assert result == "Dear Hiring Manager,"


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1])
async def test_an_empty_response_is_an_external_service_error(index: int):
    client = FakeLlmClient("   ")

    with pytest.raises(ExternalServiceError):
        await _generate(_generators(client)[index])
