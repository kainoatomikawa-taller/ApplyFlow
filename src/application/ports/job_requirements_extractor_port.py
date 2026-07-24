"""JobRequirementsExtractorPort — outbound port for LLM-driven job
requirement extraction (Epic 03).

Unlike `ResumeParserPort`, which returns its own `Parsed*` DTOs because a
resume's facts get merged into a *pre-existing* profile with dedup rules
of its own, this port returns `JobRequirements` directly — the domain
value object itself. `JobRequirements` has no identity, every field is
already optional, and there is no downstream merge/reconciliation step
(each extraction simply replaces a posting's prior result — see
`JobPosting.set_requirements`), so a second parallel "parsed" shape would
just duplicate `JobRequirements` for no benefit.

The application layer defines this abstraction; the infrastructure layer
implements it against the Epic 00 LLM layer (`LlmClientPort`, routed on
the cheap tier via `LlmTaskType.EXTRACTION`). Use cases never know which
model or provider answers the call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.value_objects.job_requirements import JobRequirements


class JobRequirementsExtractorPort(ABC):
    """Abstraction over an LLM-driven job-description-to-structured-
    requirements extractor."""

    @abstractmethod
    async def extract(self, description: str) -> JobRequirements:
        """Extract structured requirement attributes from a job posting's
        raw description text.

        Never invents a value the description doesn't support — an
        attribute the text doesn't mention, or states only ambiguously, is
        left `None`/empty on the returned `JobRequirements` rather than
        guessed. Raises `src.application.exceptions.ExternalServiceError`
        if the call fails or the model's response cannot be interpreted.
        """
