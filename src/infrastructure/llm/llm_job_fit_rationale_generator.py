"""LLM implementation of JobFitRationaleGeneratorPort.

Wraps a routed call through `LlmClientPort` behind the port interface
defined in the application layer — the use case never knows Anthropic (or
any other provider) exists. The call always uses `LlmTaskType.MATCHING`,
which `TASK_TYPE_TIERS` routes to the cheap model tier (see
`src/application/ports/llm_client_port.py`) — writing a short rationale
from an already-computed fact list is a high-volume, low-ambiguity
summarization task, not one that benefits from the stronger tier.
"""

from __future__ import annotations

from src.application.exceptions import ExternalServiceError
from src.application.ports.job_fit_rationale_generator_port import (
    JobFitRationaleGeneratorPort,
)
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType

_SYSTEM_PROMPT = """You write short, honest "why this fits" explanations \
for a candidate looking at a job posting.

You will be given the job's title and company, a list of requirements or \
preferences the candidate is already known to meet, and a list of soft \
preferences the candidate does not currently meet.

Rules:
- Write one to three short sentences in plain language. No bullet
  points, no markdown, no headings.
- Reference ONLY the facts given to you. Never invent a skill,
  credential, requirement, or company detail that wasn't provided.
- Be concise and honest: if the list of met requirements is short or
  empty, don't oversell the fit.
- Do not restate or enumerate the gaps list in your response — the gaps
  are shown to the candidate separately.
- Return ONLY the rationale text — no preamble, no quotes, no labels.
"""


class LlmJobFitRationaleGenerator(JobFitRationaleGeneratorPort):
    def __init__(self, llm_client: LlmClientPort) -> None:
        self._llm_client = llm_client

    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        matched: tuple[str, ...],
        gaps: tuple[str, ...],
    ) -> str:
        prompt = self._build_prompt(
            job_title=job_title, company=company, matched=matched, gaps=gaps
        )
        raw = await self._llm_client.complete(
            prompt, task_type=LlmTaskType.MATCHING, system=_SYSTEM_PROMPT
        )
        rationale = raw.strip()
        if not rationale:
            raise ExternalServiceError(
                "Job fit rationale generation returned an empty response."
            )
        return rationale

    @staticmethod
    def _build_prompt(
        *,
        job_title: str,
        company: str,
        matched: tuple[str, ...],
        gaps: tuple[str, ...],
    ) -> str:
        return "\n".join(
            [
                f"Job: {job_title} at {company}",
                "Requirements/preferences the candidate meets: "
                + (", ".join(matched) if matched else "none stated"),
                "Soft preferences the candidate does not currently meet: "
                + (", ".join(gaps) if gaps else "none"),
            ]
        )
