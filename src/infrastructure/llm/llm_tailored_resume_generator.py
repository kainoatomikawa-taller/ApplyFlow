"""LLM implementation of TailoredResumeGeneratorPort.

Wraps a routed call through `LlmClientPort` behind the port interface
defined in the application layer — the use case never knows Anthropic (or
any other provider) exists. The call uses `LlmTaskType.RESUME_WRITING`,
which `TASK_TYPE_TIERS` routes to the strong model tier (see
`src/application/ports/llm_client_port.py`): this is low-volume,
high-stakes writing where quality is worth the cost.

The prompt is written to make the downstream `ProvenanceGuard` a formality
rather than a scrubber — reuse the facts' own wording, one claim per line,
omit anything the facts don't cover. Every one of those instructions is
also independently enforced after the fact, because a model that ignores
them must not be able to turn its disobedience into output.
"""

from __future__ import annotations

from src.application.exceptions import ExternalServiceError
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType
from src.application.ports.tailored_resume_generator_port import (
    TailoredResumeGeneratorPort,
)

_SYSTEM_PROMPT = """You tailor a candidate's resume to one specific job \
posting.

You will be given the job's title and company, the requirements it lists, \
and a numbered list of FACTS about the candidate. The facts are the \
candidate's complete verified record.

Rules:
- Every line you write must be supported by the FACTS. Never state
  anything the facts do not say — no employer, school, tool, title,
  metric, date, or achievement of your own invention.
- Reuse the facts' own words for names, technologies, titles, numbers,
  and dates. Do not paraphrase a specific term into a different one, and
  never round, scale, or "improve" a number.
- Write one claim per line. Do not combine two facts into a single line.
- The requirements tell you what to emphasize and what order to put
  things in — they are NOT information about the candidate. If a
  requirement is not covered by the facts, leave it out entirely. Never
  claim, imply, or hedge toward experience the facts do not state.
- Plain text only: short section headings (SUMMARY, EXPERIENCE,
  EDUCATION, SKILLS) and single-line entries. No markdown, no tables.
- If the facts are too thin to fill a section, omit that section rather
  than padding it.
- Return ONLY the resume text — no preamble, no commentary, no notes
  about what you left out.
"""


class LlmTailoredResumeGenerator(TailoredResumeGeneratorPort):
    def __init__(self, llm_client: LlmClientPort) -> None:
        self._llm_client = llm_client

    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        facts: tuple[str, ...],
    ) -> str:
        prompt = self._build_prompt(
            job_title=job_title,
            company=company,
            requirements=requirements,
            facts=facts,
        )
        raw = await self._llm_client.complete(
            prompt, task_type=LlmTaskType.RESUME_WRITING, system=_SYSTEM_PROMPT
        )
        resume = raw.strip()
        if not resume:
            raise ExternalServiceError(
                "Tailored resume generation returned an empty response."
            )
        return resume

    @staticmethod
    def _build_prompt(
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        facts: tuple[str, ...],
    ) -> str:
        lines = [
            f"Job: {job_title} at {company}",
            "",
            "Requirements to emphasize (not facts about the candidate):",
        ]
        if requirements:
            lines.extend(f"- {requirement}" for requirement in requirements)
        else:
            lines.append("- none stated")
        lines.extend(["", "FACTS about the candidate (the complete record):"])
        if facts:
            lines.extend(f"{index}. {fact}" for index, fact in enumerate(facts, 1))
        else:
            lines.append("- none on file")
        return "\n".join(lines)
