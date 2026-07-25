"""Tests for LlmTailoredResumeGenerator and LlmCoverLetterGenerator — the
LLM implementations of the two generation ports.

No network calls: `LlmClientPort` is replaced with an in-memory fake, so
these run offline while proving the routing contract (RESUME_WRITING and
COVER_LETTER_WRITING -> strong tier, enforced upstream by
`TASK_TYPE_TIERS`) and that the prompt carries the candidate's facts and
keeps requirements labeled as something other than facts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from anthropic.types import TextBlock, Usage
from anthropic.types.message import Message
from pydantic import SecretStr

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import (
    TASK_TYPE_TIERS,
    LlmClientPort,
    LlmModelTier,
    LlmTaskType,
)
from src.infrastructure.config import Settings
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient
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


# ---- strong-tier routing, end to end through the real client --------------


def _anthropic_client(**model_overrides: str) -> AnthropicLlmClient:
    settings = Settings(
        _env_file=None,
        anthropic_api_key=SecretStr("sk-ant-test-key"),
        **model_overrides,
    )
    return AnthropicLlmClient(settings)


def _mock_sdk(client: AnthropicLlmClient, text: str = "EXPERIENCE") -> AsyncMock:
    response = Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    mock = AsyncMock(return_value=response)
    client._client.messages.create = mock  # type: ignore[method-assign]
    return mock


@pytest.mark.asyncio
async def test_resume_generation_reaches_the_configured_strong_model():
    """Proves the whole path, not just the tier table: the adapter picks
    RESUME_WRITING, TASK_TYPE_TIERS maps that to STRONG, and the client
    resolves STRONG to ANTHROPIC_MODEL_STRONG."""
    client = _anthropic_client(
        anthropic_model_cheap="cheap-test-model",
        anthropic_model_strong="strong-test-model",
    )
    mock_create = _mock_sdk(client)

    await _generate(LlmTailoredResumeGenerator(client))

    _, kwargs = mock_create.await_args
    assert kwargs["model"] == "strong-test-model"


@pytest.mark.asyncio
async def test_resume_generation_uses_sonnet_by_default():
    """The documented default for the strong tier — a resume is low-volume,
    high-stakes writing and is not quietly downgraded to the cheap model."""
    client = _anthropic_client()
    mock_create = _mock_sdk(client)

    await _generate(LlmTailoredResumeGenerator(client))

    _, kwargs = mock_create.await_args
    assert kwargs["model"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_the_resume_tier_mapping_is_the_strong_one():
    assert TASK_TYPE_TIERS[LlmTaskType.RESUME_WRITING] is LlmModelTier.STRONG


# ---- ATS-safe instructions ------------------------------------------------


@pytest.mark.asyncio
async def test_the_resume_prompt_asks_for_ats_safe_structure():
    client = FakeLlmClient("draft")

    await _generate(LlmTailoredResumeGenerator(client))

    system = (client.calls[0][2] or "").lower()
    assert "applicant tracking" in system
    assert "no tables" in system
    assert "no markdown" in system
    assert "single column" in system
    for heading in ("summary", "experience", "education", "skills"):
        assert heading in system


@pytest.mark.asyncio
async def test_the_resume_prompt_allows_keyword_alignment_only_where_facts_back_it():
    client = FakeLlmClient("draft")

    await _generate(LlmTailoredResumeGenerator(client))

    system = " ".join((client.calls[0][2] or "").split())
    assert "use the posting's wording for it" in system
    assert "never to work a keyword in" in system


@pytest.mark.asyncio
async def test_the_resume_prompt_asks_for_role_relevant_ordering():
    client = FakeLlmClient("draft")

    await _generate(LlmTailoredResumeGenerator(client))

    assert "Lead with what this posting asks for" in (client.calls[0][2] or "")


# ---- cover letter: strong tier, answer reuse, tone --------------------------


@pytest.mark.asyncio
async def test_cover_letter_generation_reaches_the_configured_strong_model():
    """The whole path, not just the tier table: the adapter picks
    COVER_LETTER_WRITING, TASK_TYPE_TIERS maps that to STRONG, and the client
    resolves STRONG to ANTHROPIC_MODEL_STRONG."""
    client = _anthropic_client(
        anthropic_model_cheap="cheap-test-model",
        anthropic_model_strong="strong-test-model",
    )
    mock_create = _mock_sdk(client, text="Dear Hiring Manager,")

    await _generate(LlmCoverLetterGenerator(client))

    _, kwargs = mock_create.await_args
    assert kwargs["model"] == "strong-test-model"


@pytest.mark.asyncio
async def test_cover_letter_generation_uses_sonnet_by_default():
    client = _anthropic_client()
    mock_create = _mock_sdk(client, text="Dear Hiring Manager,")

    await _generate(LlmCoverLetterGenerator(client))

    _, kwargs = mock_create.await_args
    assert kwargs["model"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_the_cover_letter_tier_mapping_is_the_strong_one():
    assert TASK_TYPE_TIERS[LlmTaskType.COVER_LETTER_WRITING] is LlmModelTier.STRONG


@pytest.mark.asyncio
async def test_relevant_answers_reach_the_prompt_as_their_own_labeled_block():
    client = FakeLlmClient("draft")

    await LlmCoverLetterGenerator(client).generate(
        job_title="Senior Platform Engineer",
        company="Globex",
        requirements=_REQUIREMENTS,
        facts=_FACTS,
        relevant_answers=("Asked 'Have you led a team?', answered: I led five.",),
    )

    prompt = client.calls[0][0]
    assert "THE CANDIDATE'S OWN ANSWERS" in prompt
    assert "Asked 'Have you led a team?', answered: I led five." in prompt


@pytest.mark.asyncio
async def test_the_answers_block_says_they_are_already_among_the_facts():
    """The block is emphasis, not extra permission — the prompt says so, so
    a model cannot read it as a second, looser source."""
    client = FakeLlmClient("draft")

    await LlmCoverLetterGenerator(client).generate(
        job_title="Senior Platform Engineer",
        company="Globex",
        requirements=(),
        facts=_FACTS,
        relevant_answers=("Asked 'Q', answered: A",),
    )

    assert "already included in the facts above" in client.calls[0][0]


@pytest.mark.asyncio
async def test_with_no_relevant_answers_the_prompt_says_so_explicitly():
    """An absent section would invite the model to supply the specificity
    the answers would have carried."""
    client = FakeLlmClient("draft")

    await _generate(LlmCoverLetterGenerator(client))

    prompt = client.calls[0][0]
    assert "THE CANDIDATE'S OWN ANSWERS" in prompt
    assert "none especially relevant; write from the facts alone" in prompt


@pytest.mark.asyncio
async def test_the_letter_prompt_forbids_inventing_an_anecdote_in_place_of_answers():
    client = FakeLlmClient("draft")

    await _generate(LlmCoverLetterGenerator(client))

    system = " ".join((client.calls[0][2] or "").split())
    assert "Never invent the kind of specific anecdote an answer would have" in system


@pytest.mark.asyncio
async def test_the_letter_prompt_requires_keeping_an_answers_wording_and_scope():
    client = FakeLlmClient("draft")

    await _generate(LlmCoverLetterGenerator(client))

    system = " ".join((client.calls[0][2] or "").split())
    assert "Keep their wording and their scope" in system
    assert "do not upgrade it" in system


@pytest.mark.asyncio
async def test_the_letter_prompt_demands_a_professional_role_specific_tone():
    client = FakeLlmClient("draft")

    await _generate(LlmCoverLetterGenerator(client))

    system = " ".join((client.calls[0][2] or "").split())
    assert "Address the role by title and the company by name" in system
    assert "could be sent to any employer is worthless" in system
    assert "No gushing, no superlatives, no buzzwords" in system
    assert "keen interest" in system  # named as a phrase to avoid
    assert "do not discuss salary" in system


@pytest.mark.asyncio
async def test_the_letter_prompt_asks_for_plain_text_with_a_standard_open_and_close():
    client = FakeLlmClient("draft")

    await _generate(LlmCoverLetterGenerator(client))

    system = " ".join((client.calls[0][2] or "").split())
    assert "Dear Hiring Manager," in system
    assert "Sincerely," in system
    assert "No markdown" in system
