"""CoverLetterGeneratorPort — outbound port for LLM-driven cover-letter
writing for one job posting.

Sibling of `TailoredResumeGeneratorPort`: same fact-strings-only boundary,
same "the result is a draft, not output" contract (every line goes through
`ProvenanceGuard` in `GenerateCoverLetter` first). It stays a separate port
rather than a mode flag on one generator because the two produce different
artifacts from different prompts on different LLM task types
(`LlmTaskType.COVER_LETTER_WRITING` here), and a caller asking for one
should not be able to receive the other.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CoverLetterGeneratorPort(ABC):
    """Abstraction over an LLM-driven cover-letter writer."""

    @abstractmethod
    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        facts: tuple[str, ...],
        relevant_answers: tuple[str, ...] = (),
    ) -> str:
        """Return a plain-text cover letter drawn only from `facts` (the
        candidate's provenance-backed facts, already flattened to
        strings), addressed to the `job_title` role at `company`.

        One assertion per line, since the guard downstream accepts or
        drops whole lines. `requirements` guides which of the candidate's
        real facts to foreground — never what to claim: a requirement
        `facts` doesn't cover must go unmentioned, not be asserted or
        hedged into an implication.

        `relevant_answers` is the subset of `facts` that came from what the
        candidate said in their own words and that this job asked about (see
        `RelevantAnswerSelector`) — the material most worth building the
        letter around, since it is specific and already phrased the way the
        candidate would phrase it. It is a *subset*, never a substitute:
        everything in it is also in `facts`, so an implementation that
        ignores it still writes only attested claims, and one that leans on
        it gains no license to assert anything more. Empty means nothing on
        file was especially relevant, which is normal.

        Raises `src.application.exceptions.ExternalServiceError` if the call
        fails or returns an empty response.
        """
