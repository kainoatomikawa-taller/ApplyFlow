"""GenerateCoverLetter use case — writes a cover letter for one job
posting, with every line validated against the candidate's
provenance-backed facts before it is returned.

Mirrors `GenerateTailoredResume`'s generate-then-guard order for the same
reason, and is not implemented in terms of it (use cases never depend on
one another) — the shared parts live in `ProvenanceFactAssembler` and
`ProvenanceGuard` instead, so the two flows cannot drift on what counts as
evidence. A cover letter needs the guard at least as much as a resume does:
prose invites the model to editorialize a candidate's experience into
something more impressive than their record states, and this is where that
gets removed.
"""

from __future__ import annotations

from src.application.dtos.generation_dtos import (
    GenerateCoverLetterInput,
    GeneratedDocumentKind,
    GuardedDocumentOutput,
    ProvenanceViolationOutput,
)
from src.application.ports.cover_letter_generator_port import CoverLetterGeneratorPort
from src.application.services.generation_guard_audit import GenerationGuardAudit
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.services.provenance_guard import ProvenanceGuard
from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.value_objects.job_requirements import JobRequirements


class GenerateCoverLetter:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        fact_assembler: ProvenanceFactAssembler,
        generator: CoverLetterGeneratorPort,
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

    async def execute(self, dto: GenerateCoverLetterInput) -> GuardedDocumentOutput:
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
            document_kind=GeneratedDocumentKind.COVER_LETTER,
            user_id=dto.user_id,
            job_posting_id=posting.id,
            guarded=guarded,
        )

        return GuardedDocumentOutput(
            job_posting_id=posting.id,
            document_kind=GeneratedDocumentKind.COVER_LETTER.value,
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
