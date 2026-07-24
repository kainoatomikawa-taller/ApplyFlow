"""GapResolutionQuestionGeneratorPort — outbound port for LLM-driven
generation of neutrally-phrased gap-resolution questions.

The application layer defines this abstraction; the infrastructure layer
implements it against the Epic 00 LLM layer (`LlmClientPort`, routed on
the cheap tier via `LlmTaskType.MATCHING`). Use cases never know which
model or provider answers the call.

Callers pass only the plain gap description string — never a raw
`JobRequirements` or `UserProfile` — so the boundary of what's safe/
relevant to send to a third-party LLM stays an explicit, reviewable
decision made by the calling use case, not an implicit one made inside
the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class GapResolutionQuestionGeneratorPort(ABC):
    """Abstraction over an LLM-driven, neutrally-phrased question writer."""

    @abstractmethod
    async def generate_question(self, *, gap: str) -> str:
        """Return one short, open-ended question that invites the
        candidate to share genuine experience relevant to `gap` — a job
        requirement/preference nothing in their known facts currently
        backs up.

        The question must stay neutral: it never implies the candidate
        already has (or lacks) the experience, and never words things so
        that claiming it is the easier or expected answer. It must never
        coach the candidate toward a more impressive-sounding answer than
        their real experience supports.

        Raises `src.application.exceptions.ExternalServiceError` if the
        call fails or returns an empty response.
        """
