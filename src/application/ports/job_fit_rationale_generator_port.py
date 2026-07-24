"""JobFitRationaleGeneratorPort — outbound port for LLM-driven "why this
fits" rationale generation.

The application layer defines this abstraction; the infrastructure layer
implements it against the Epic 00 LLM layer (`LlmClientPort`, routed on
the cheap tier via `LlmTaskType.MATCHING`). Use cases never know which
model or provider answers the call.

Callers pass only plain, already-computed fact strings — never a raw
`UserProfile` or `JobPosting` — so the boundary of what's safe/relevant to
send to a third-party LLM stays an explicit, reviewable decision made by
the calling use case, not an implicit one made inside the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class JobFitRationaleGeneratorPort(ABC):
    """Abstraction over an LLM-driven job-fit rationale writer."""

    @abstractmethod
    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        matched: tuple[str, ...],
        gaps: tuple[str, ...],
    ) -> str:
        """Return a short, honest "why this fits" rationale (a sentence or
        two), grounded only in `matched` (requirements/preferences the
        candidate is already known to meet) and `gaps` (soft preferences
        they don't currently meet).

        Never invents a skill, credential, or requirement not present in
        `matched`/`gaps`. Raises
        `src.application.exceptions.ExternalServiceError` if the call
        fails or returns an empty response.
        """
