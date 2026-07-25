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
    ) -> str:
        """Return a plain-text cover letter drawn only from `facts` (the
        candidate's provenance-backed facts, already flattened to
        strings), addressed to the `job_title` role at `company`.

        One assertion per line, since the guard downstream accepts or
        drops whole lines. `requirements` guides which of the candidate's
        real facts to foreground — never what to claim: a requirement
        `facts` doesn't cover must go unmentioned, not be asserted or
        hedged into an implication. Raises
        `src.application.exceptions.ExternalServiceError` if the call
        fails or returns an empty response.
        """
