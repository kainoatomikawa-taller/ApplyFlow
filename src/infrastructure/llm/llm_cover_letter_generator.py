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
doesn't. That guard also does much of the tone enforcement for free:
"seasoned" and "world-class" are unattested terms, so they are stripped
whether or not the model was told to avoid them.

`relevant_answers` is passed through as its own labeled block. Those are the
candidate's own sentences about what this job asked about, which is the
best material a letter can be built from — specific, already in their voice,
and (unlike the profile's dated entries) written as prose. Listing them
separately tells the model where to look; it grants no additional license,
since every one of them is also in the fact list the guard validates against.

The second failure mode is genericism: a letter that could be sent to any
company says nothing, and reviewers discard it. So the prompt requires the
role and company by name and requires each paragraph to do a distinct job,
rather than padding a template with adjectives.
"""

from __future__ import annotations

from src.application.exceptions import ExternalServiceError
from src.application.ports.cover_letter_generator_port import CoverLetterGeneratorPort
from src.application.ports.llm_client_port import LlmClientPort, LlmTaskType

_SYSTEM_PROMPT = """You write a short, honest cover letter for one \
specific job posting.

You will be given the job's title and company, the requirements it lists, \
a numbered list of FACTS about the candidate, and sometimes a shorter list \
of THE CANDIDATE'S OWN ANSWERS relevant to this job. The facts are the \
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

Using the candidate's own answers:
- When ANSWERS are given, build the middle of the letter around them.
  They are what the candidate said about exactly what this job asked
  about, in their own words, so they are more specific and more theirs
  than anything you could compose from the dated entries.
- Keep their wording and their scope. If an answer says "I led a team of
  five engineers", write that; do not upgrade it to "led engineering" or
  round the number.
- Do not quote an answer's question back, and do not mention that the
  candidate answered a question. Write the substance as their experience.
- If no answers are given, write from the FACTS alone. Never invent the
  kind of specific anecdote an answer would have supplied.

Tone and structure — professional, specific to this role:
- Address the role by title and the company by name. A letter that could
  be sent to any employer is worthless; every paragraph should be one that
  only makes sense for this posting.
- Plain, direct, professional register. No gushing, no superlatives, no
  buzzwords, no exclamation marks, and never "I am writing to express my
  keen interest".
- Say what the candidate has done and how it bears on this role. Do not
  plead, do not flatter the company, do not discuss salary, and do not
  apologize for anything the facts don't cover.
- Four short paragraphs at most, each doing distinct work: why this role,
  the most relevant attested experience, one more supporting piece, a
  brief close.
- Plain text only, with a "Dear Hiring Manager," opening and a
  "Sincerely," close followed by the candidate's name. No markdown, no
  bullet points, no headings, plain ASCII punctuation.
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
        relevant_answers: tuple[str, ...] = (),
    ) -> str:
        prompt = self._build_prompt(
            job_title=job_title,
            company=company,
            requirements=requirements,
            facts=facts,
            relevant_answers=relevant_answers,
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
        relevant_answers: tuple[str, ...],
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
        # Always present, even when empty: the model is told what to do in
        # both cases, and an absent section invites it to supply the
        # specificity the answers would have carried.
        lines.extend(
            [
                "",
                "THE CANDIDATE'S OWN ANSWERS most relevant to this job "
                "(already included in the facts above — build the letter "
                "around these):",
            ]
        )
        if relevant_answers:
            lines.extend(f"- {answer}" for answer in relevant_answers)
        else:
            lines.append("- none especially relevant; write from the facts alone")
        return "\n".join(lines)
