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

It shares the resume flow's attestation rule too (`UnattestedGenerationError`
when no surviving line traces to a candidate fact): a letter of pure
salutation and enthusiasm passes the guard while saying nothing about the
candidate, and handing that back as finished work would be the same failure
in a different shape. It shares `normalize_plain_text` as well, so stray
markdown never reaches a reader — but not `drop_empty_sections`, since a
letter has no section headings to hollow out.

Archiving is shared too, through `ApplicationDocumentArchive` and for the
same reason: what actually went out has to be readable later without
regenerating it (see `ApplicationDocument`). A letter is arguably the more
important of the two to keep — it is the document whose exact wording a
candidate will be asked about in an interview.

Where it diverges from the resume flow is answer reuse. Both documents are
validated against the candidate's remembered answers, but only the letter is
*built* from them: `RelevantAnswerSelector` picks the few this job actually
asked about and they are handed to the generator as the material to work
from. That is the difference between a letter of dated job entries and one
that says something specific in the candidate's own voice. The selection
narrows the prompt only — the guard still validates against every attested
fact, so an answer being judged off-topic can never make a true claim
unsupportable.
"""

from __future__ import annotations

from src.application.dtos.generation_dtos import (
    GenerateCoverLetterInput,
    GuardedDocumentOutput,
    ProvenanceViolationOutput,
)
from src.application.exceptions import UnattestedGenerationError
from src.application.ports.cover_letter_generator_port import CoverLetterGeneratorPort
from src.application.services.application_document_archive import (
    ApplicationDocumentArchive,
)
from src.application.services.generation_guard_audit import GenerationGuardAudit
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.application.services.relevant_answer_selector import RelevantAnswerSelector
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.services.ats_safe_text_formatter import AtsSafeTextFormatter
from src.domain.services.provenance_guard import ProvenanceGuard
from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.job_requirements import JobRequirements


class GenerateCoverLetter:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        fact_assembler: ProvenanceFactAssembler,
        generator: CoverLetterGeneratorPort,
        archive: ApplicationDocumentArchive,
        answer_selector: RelevantAnswerSelector | None = None,
        guard: ProvenanceGuard | None = None,
        classifier: RequirementClassifier | None = None,
        audit: GenerationGuardAudit | None = None,
        formatter: AtsSafeTextFormatter | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._fact_assembler = fact_assembler
        self._generator = generator
        self._archive = archive
        # Optional: answer highlighting needs an embedding provider, and a
        # letter is still writable without it — the full fact corpus is
        # always there. Absent a selector, nothing is foregrounded and the
        # generator is told so explicitly.
        self._answer_selector = answer_selector
        self._guard = guard or ProvenanceGuard()
        self._classifier = classifier or RequirementClassifier()
        self._audit = audit or GenerationGuardAudit()
        self._formatter = formatter or AtsSafeTextFormatter()

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

        relevant_answers = await self._select_relevant_answers(
            user_id=dto.user_id,
            job_title=posting.title,
            requirements=requirements,
        )

        draft = await self._generator.generate(
            job_title=posting.title,
            company=posting.company,
            requirements=requirements,
            facts=tuple(fact.text for fact in facts),
            relevant_answers=relevant_answers,
        )

        guarded = self._guard.enforce(
            self._formatter.normalize_plain_text(draft),
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
        if not guarded.has_attested_content:
            raise UnattestedGenerationError(
                document_kind=GeneratedDocumentKind.COVER_LETTER.value,
                unsupported_terms=guarded.unsupported_terms,
            )

        snapshot = await self._archive.store(
            user_id=dto.user_id,
            job_posting_id=posting.id,
            document_kind=GeneratedDocumentKind.COVER_LETTER,
            content=guarded.content,
            backing_sources=guarded.backing_sources,
        )

        return GuardedDocumentOutput(
            document_id=snapshot.id,
            job_posting_id=posting.id,
            document_kind=GeneratedDocumentKind.COVER_LETTER.value,
            content=guarded.content,
            version=snapshot.version,
            backing_sources=[source.value for source in guarded.backing_sources],
            violations=[
                ProvenanceViolationOutput(
                    line=violation.line,
                    unsupported_terms=list(violation.unsupported_terms),
                )
                for violation in guarded.violations
            ],
        )

    async def _select_relevant_answers(
        self, *, user_id: str, job_title: str, requirements: tuple[str, ...]
    ) -> tuple[str, ...]:
        """The remembered answers this job asked about, as plain strings for
        the generator.

        The relevance query is the job's own words — its title plus the
        requirements it lists — because that is what the letter has to speak
        to. Note this is the posting's text used as a *search query*, not as
        evidence: it selects among the candidate's real answers and never
        becomes one (see `ProvenanceGuard` on why requirement text is kept
        out of the guard's corpus).
        """
        if self._answer_selector is None:
            return ()
        selected = await self._answer_selector.select(
            user_id=user_id,
            query=" ".join((job_title, *requirements)),
        )
        return tuple(fact.text for fact in selected)
