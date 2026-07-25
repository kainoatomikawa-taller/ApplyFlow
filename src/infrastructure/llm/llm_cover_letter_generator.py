"""LLM implementation of CoverLetterGeneratorPort.

Sibling of `LlmTailoredResumeGenerator`: same fact-strings-in, draft-out
contract, routed on `LlmTaskType.COVER_LETTER_WRITING` (the strong tier —
low-volume, high-stakes writing).

The prompt fights the failure mode specific to letters: prose rewards
enthusiasm, and enthusiasm is where a model starts describing a candidate
as "seasoned", "extensive", or "a proven leader" on no evidence. Interest
in the role is fine — it is the candidate's own stance, not a claim about
their history — but any statement about what they have actually done has to
come from the facts, and `ProvenanceGuard` removes it downstream if it
doesn't.
"""

from __future__ import annotations

from src.application.exceptions import ExternalServiceError
from src.application.ports.cover_letter_generator_port import CoverLetterGeneratorPort
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType

_SYSTEM_PROMPT = """You write a short, honest cover letter for one \
specific job posting.

You will be given the job's title and company, the requirements it lists, \
and a numbered list of FACTS about the candidate. The facts are the \
candidate's complete verified record.

Rules:
- Every claim about the candidate must be supported by the FACTS. Never
  state anything the facts do not say — no employer, school, tool, title,
  metric, date, or achievement of your own invention.
- Reuse the facts' own words for names, technologies, titles, numbers,
  and dates. Never round, scale, or "improve" a number.
- No unearned praise. Do not describe the candidate as senior, seasoned,
  expert, extensive, proven, or passionate unless a fact says so. Saying
  they are interested in this role is fine; characterizing their ability
  is not.
- Write one claim per sentence and put each sentence on its own line.
- The requirements tell you which of the candidate's real facts to
  foreground — they are NOT information about the candidate. If a
  requirement is not covered by the facts, leave it out. Never claim,
  imply, or hedge toward experience the facts do not state.
- Plain text only, four short paragraphs at most, with a "Dear Hiring
  Manager," opening and a "Sincerely," close. No markdown.
- Return ONLY the letter text — no preamble, no commentary, no notes
  about what you left out.
"""


class LlmCoverLetterGenerator(CoverLetterGeneratorPort):
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
            prompt, task_type=LlmTaskType.COVER_LETTER_WRITING, system=_SYSTEM_PROMPT
        )
        letter = raw.strip()
        if not letter:
            raise ExternalServiceError(
                "Cover letter generation returned an empty response."
            )
        return letter

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
            "Requirements to address where the facts allow "
            "(not facts about the candidate):",
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
