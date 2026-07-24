"""LLM implementation of GapResolutionQuestionGeneratorPort.

Wraps a routed call through `LlmClientPort` behind the port interface
defined in the application layer — the use case never knows Anthropic (or
any other provider) exists. The call always uses `LlmTaskType.MATCHING`,
which `TASK_TYPE_TIERS` routes to the cheap model tier (see
`src/application/ports/llm_client_port.py`) — phrasing one short question
from a single gap description is a high-volume, low-ambiguity generation
task, not one that benefits from the stronger tier.
"""

from __future__ import annotations

from src.application.exceptions import ExternalServiceError
from src.application.ports.gap_resolution_question_generator_port import (
    GapResolutionQuestionGeneratorPort,
)
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType

_SYSTEM_PROMPT = """You write short, neutral follow-up questions for a \
candidate filling out a job application.

You will be given one job requirement or preference that nothing in the
candidate's known facts currently confirms they meet.

Rules:
- Write ONE short, open-ended question that invites the candidate to
  share real experience relevant to this requirement, if they have any.
- Stay strictly neutral. Never imply the candidate already has — or
  lacks — this experience, and never word the question so that claiming
  it is the easier or expected answer. A candidate with nothing to add
  should feel just as comfortable answering "no" as "yes".
- Never coach, hint at, or suggest how to phrase an answer that would
  make the candidate sound more qualified than their real experience
  supports.
- Do not just restate the requirement as a yes/no question in the
  employer's own words (e.g. don't turn "5+ years of Kubernetes" into
  "Do you have 5+ years of Kubernetes experience?"). Ask about the
  underlying experience in plain, general terms instead (e.g. "Have you
  worked with Kubernetes or similar tools, and if so, how much?").
- Output ONLY the question text — no preamble, no quotes, no labels, no
  numbering.
"""


class LlmGapResolutionQuestionGenerator(GapResolutionQuestionGeneratorPort):
    def __init__(self, llm_client: LlmClientPort) -> None:
        self._llm_client = llm_client

    async def generate_question(self, *, gap: str) -> str:
        prompt = f"Job requirement/preference not yet confirmed: {gap}"
        raw = await self._llm_client.complete(
            prompt, task_type=LlmTaskType.MATCHING, system=_SYSTEM_PROMPT
        )
        question = raw.strip()
        if not question:
            raise ExternalServiceError(
                "Gap resolution question generation returned an empty response."
            )
        return question
