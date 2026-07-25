"""GenerateTailoredResume use case — produces a resume tailored to one job
posting, with every line validated against the candidate's
provenance-backed facts before it is returned.

The order here is the point: generate, then guard, then return. The
generator's output is never the use case's output. There is no branch, flag,
or "trusted generator" path that skips `ProvenanceGuard` — the only value
this use case can return is post-guard content, so shipping an unvalidated
draft would take a code change, not a misconfiguration.

What the posting contributes is deliberately asymmetric. Its requirements
reach the *generator*, where they steer which of the candidate's real facts
to foreground, but never the *guard*, which is given only the posting's
identifying title/company/location as referable context. A requirement is
what the employer asked for; treating it as evidence would let the model
claim every requirement as the candidate's own experience (see
`ProvenanceGuard`).
"""

from __future__ import annotations

from src.application.dtos.generation_dtos import (
    GeneratedDocumentKind,
    GenerateTailoredResumeInput,
    GuardedDocumentOutput,
    ProvenanceViolationOutput,
)
from src.application.ports.tailored_resume_generator_port import (
    TailoredResumeGeneratorPort,
)
from src.application.services.generation_guard_audit import GenerationGuardAudit
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.services.provenance_guard import ProvenanceGuard
from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.value_objects.job_requirements import JobRequirements


class GenerateTailoredResume:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        fact_assembler: ProvenanceFactAssembler,
        generator: TailoredResumeGeneratorPort,
        guard: ProvenanceGuard | None = None,
        classifier: RequirementClassifier | None = None,
        audit: GenerationGuardAudit | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._fact_assembler = fact_assembler
        self._generator = generator
        self._guard = guard or ProvenanceGuard()
        self._classifier = classifier or RequirementClassifier()
        self._audit = audit or GenerationGuardAudit()

    async def execute(self, dto: GenerateTailoredResumeInput) -> GuardedDocumentOutput:
        posting = await self._job_posting_repository.get_by_id(dto.job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        facts = await self._fact_assembler.assemble(dto.user_id)

        classification = self._classifier.classify(
            posting.requirements or JobRequirements()
        )
        requirements = tuple(
            item.description for item in (*classification.hard, *classification.soft)
        )

        draft = await self._generator.generate(
            job_title=posting.title,
            company=posting.company,
            requirements=requirements,
            facts=tuple(fact.text for fact in facts),
        )

        guarded = self._guard.enforce(
            draft,
            facts=facts,
            context_terms=tuple(
                term
                for term in (posting.title, posting.company, posting.location)
                if term
            ),
        )
        self._audit.record(
            document_kind=GeneratedDocumentKind.TAILORED_RESUME,
            user_id=dto.user_id,
            job_posting_id=posting.id,
            guarded=guarded,
        )

        return GuardedDocumentOutput(
            job_posting_id=posting.id,
            document_kind=GeneratedDocumentKind.TAILORED_RESUME.value,
            content=guarded.content,
            backing_sources=[source.value for source in guarded.backing_sources],
            violations=[
                ProvenanceViolationOutput(
                    line=violation.line,
                    unsupported_terms=list(violation.unsupported_terms),
                )
                for violation in guarded.violations
            ],
        )
