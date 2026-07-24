"""LLM implementation of RequirementGapDetectorPort.

Wraps a routed call through `LlmClientPort` behind the port interface
defined in the application layer — the use case never knows Anthropic (or
any other provider) exists. The call always uses `LlmTaskType.MATCHING`,
which `TASK_TYPE_TIERS` routes to the cheap model tier (see
`src/application/ports/llm_client_port.py`) — checking a requirement list
against an already-computed fact list is a high-volume, low-ambiguity
matching task, not one that benefits from the stronger tier.

Fabrication is guarded against twice over: the system prompt instructs the
model to copy gap lines verbatim from the given requirements, and
`_extract_gaps` below independently verifies that against the original
list — any line the model returns that isn't an exact (case-insensitive)
match for one of `requirements` is silently dropped rather than trusted.
"""

from __future__ import annotations

from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.application.ports.requirement_gap_detector_port import (
    RequirementGapDetectorPort,
)

_SYSTEM_PROMPT = """You check whether a job's stated requirements are \
backed up by known facts about a candidate.

You will be given the job's title and company, a numbered list of the
job's requirements/preferences, and a list of facts already known about
the candidate — drawn from their profile and from answers they've given on
past applications.

Rules:
- A requirement is a GAP whenever no fact in the candidate list confirms
  it is met — including when the facts are simply silent on it. Silence
  is not evidence of a match.
- Never invent a candidate fact that wasn't given, and never invent,
  paraphrase, or add detail to a requirement that wasn't given.
- Every gap you report must be copied verbatim, character-for-character,
  from the requirements list you were given.
- Output ONLY the gaps, one per line, in the same order they appear in the
  requirements list. If every requirement is backed by a fact, output
  exactly one line: NONE.
- No numbering, no bullet points, no explanations, no other text.
"""


class LlmRequirementGapDetector(RequirementGapDetectorPort):
    def __init__(self, llm_client: LlmClientPort) -> None:
        self._llm_client = llm_client

    async def detect_gaps(
        self,
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        candidate_facts: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not requirements:
            return ()

        prompt = self._build_prompt(
            job_title=job_title,
            company=company,
            requirements=requirements,
            candidate_facts=candidate_facts,
        )
        raw = await self._llm_client.complete(
            prompt, task_type=LlmTaskType.MATCHING, system=_SYSTEM_PROMPT
        )
        return self._extract_gaps(raw, requirements)

    @staticmethod
    def _build_prompt(
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        candidate_facts: tuple[str, ...],
    ) -> str:
        numbered_requirements = "\n".join(
            f"{i}. {requirement}" for i, requirement in enumerate(requirements, 1)
        )
        facts = "\n".join(f"- {fact}" for fact in candidate_facts) or "- none known"
        return "\n".join(
            [
                f"Job: {job_title} at {company}",
                "Requirements/preferences:",
                numbered_requirements,
                "Known candidate facts:",
                facts,
            ]
        )

    @staticmethod
    def _extract_gaps(raw: str, requirements: tuple[str, ...]) -> tuple[str, ...]:
        reported = {line.strip().lower() for line in raw.splitlines() if line.strip()}
        return tuple(
            requirement
            for requirement in requirements
            if requirement.strip().lower() in reported
        )
