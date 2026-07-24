"""RequirementGapDetectorPort — outbound port for LLM-driven detection of
job requirements a candidate's known facts don't back up.

The application layer defines this abstraction; the infrastructure layer
implements it against the Epic 00 LLM layer (`LlmClientPort`, routed on
the cheap tier via `LlmTaskType.MATCHING`). Use cases never know which
model or provider answers the call.

Callers pass only plain, already-computed strings — a job's requirement
descriptions and the candidate's known facts (profile + answer memory) —
never a raw `UserProfile`, `JobRequirements`, or `AnswerMemory`, so the
boundary of what's safe/relevant to send to a third-party LLM stays an
explicit, reviewable decision made by the calling use case, not an
implicit one made inside the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class RequirementGapDetectorPort(ABC):
    """Abstraction over an LLM-driven check of requirements against facts."""

    @abstractmethod
    async def detect_gaps(
        self,
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        candidate_facts: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Return the subset of `requirements` that isn't confirmed as met
        by any fact in `candidate_facts` — a requirement stays a gap
        whenever the facts are silent on it, not only when they
        contradict it, since an unbacked requirement is exactly what a
        gap is here.

        The returned tuple only ever contains entries copied verbatim from
        `requirements`, in their original order — never a paraphrase, a
        fabricated requirement, or a fact not present in `candidate_facts`.
        Returns an empty tuple when every requirement is backed by a fact,
        or when `requirements` itself is empty. Raises
        `src.application.exceptions.ExternalServiceError` if the call
        fails.
        """
