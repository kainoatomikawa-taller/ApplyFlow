"""Opt-in end-to-end test against the real Anthropic API.

Skipped by default so `pytest` never spends money or needs network access.
Run it deliberately once a real key is configured:

    RUN_LIVE_LLM_TEST=1 ANTHROPIC_API_KEY=sk-ant-... pytest \
        tests/infrastructure/test_anthropic_llm_client_live.py
"""

import os

import pytest

from src.infrastructure.config import get_settings
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TEST") != "1",
    reason="opt-in: set RUN_LIVE_LLM_TEST=1 with a real ANTHROPIC_API_KEY to run",
)


@pytest.mark.asyncio
async def test_live_completion_against_the_real_anthropic_api():
    get_settings.cache_clear()
    client = AnthropicLlmClient(get_settings())

    text = await client.complete(
        "Reply with exactly one word, lowercase, no punctuation: pong"
    )

    assert "pong" in text.lower()
