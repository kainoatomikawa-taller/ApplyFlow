"""TailoredResumeGeneratorPort — outbound port for LLM-driven tailoring of
a resume to one job posting.

The application layer defines this abstraction; the infrastructure layer
implements it against the Epic 00 LLM layer (`LlmClientPort`, routed via
`LlmTaskType.RESUME_WRITING`). Use cases never know which model or
provider answers the call.

Callers pass only plain, already-assembled fact strings — never a raw
`UserProfile`, `AnswerMemory`, or `JobPosting` — so the boundary of what's
safe/relevant to send to a third-party LLM stays an explicit, reviewable
decision made by the calling use case, not an implicit one made inside the
adapter (same convention as `JobFitRationaleGeneratorPort`).

Whatever comes back is a draft, not output: `GenerateTailoredResume` runs
every line through `ProvenanceGuard` before anything reaches a caller. An
implementation is expected to instruct its model to stay inside `facts`,
but nothing downstream trusts that it did.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TailoredResumeGeneratorPort(ABC):
    """Abstraction over an LLM-driven resume tailoring writer."""

    @abstractmethod
    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        facts: tuple[str, ...],
    ) -> str:
        """Return a plain-text tailored resume drawn only from `facts`
        (the candidate's provenance-backed facts, already flattened to
        strings), emphasizing what `requirements` asks for.

        One assertion per line, since the guard downstream accepts or
        drops whole lines: a line that bundles a supported claim with an
        unsupported one costs the candidate both.

        `requirements` guides emphasis and ordering only — it is never
        evidence about the candidate, so a requirement `facts` doesn't
        cover must simply go unmentioned rather than be claimed. Raises
        `src.application.exceptions.ExternalServiceError` if the call
        fails or returns an empty response.
        """
