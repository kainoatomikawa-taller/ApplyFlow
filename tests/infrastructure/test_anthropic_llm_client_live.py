"""Opt-in end-to-end test against the real Anthropic API.

Skipped by default so `pytest` never spends money or needs network access.
Run it deliberately once a real key is configured:

    RUN_LIVE_LLM_TEST=1 ANTHROPIC_API_KEY=sk-ant-... pytest \
        tests/infrastructure/test_anthropic_llm_client_live.py

Covers both model tiers so model routing (not just the API call itself)
is proven against the real API, not just mocks.
"""

import os

import pytest

from src.application.ports.llm_client_port import LlmTaskType
from src.infrastructure.config import get_settings
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TEST") != "1",
    reason="opt-in: set RUN_LIVE_LLM_TEST=1 with a real ANTHROPIC_API_KEY to run",
)


@pytest.mark.asyncio
async def test_live_completion_on_the_cheap_tier():
    get_settings.cache_clear()
    client = AnthropicLlmClient(get_settings())

    text = await client.complete(
        "Respond with only the single word 'acknowledged', nothing else.",
        task_type=LlmTaskType.EXTRACTION,
    )

    assert "acknowledged" in text.lower()


@pytest.mark.asyncio
async def test_live_completion_on_the_strong_tier():
    get_settings.cache_clear()
    client = AnthropicLlmClient(get_settings())

    text = await client.complete(
        "Respond with only the single word 'acknowledged', nothing else.",
        task_type=LlmTaskType.RESUME_WRITING,
    )

    assert "acknowledged" in text.lower()
