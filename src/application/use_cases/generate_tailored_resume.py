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

The full pipeline is normalize -> guard -> tidy -> attest -> export -> archive:

1. `AtsSafeTextFormatter.normalize_plain_text` flattens the draft to
   ATS-parseable plain text first, so the text the guard validates is the
   text that ships and no post-guard rewriting is needed.
2. `ProvenanceGuard` removes every line the candidate's facts don't back.
3. `AtsSafeTextFormatter.drop_empty_sections` clears headings left
   standing over nothing — the shape a stripped fabrication leaves, and the
   difference between a shorter resume and a broken-looking one.
4. If no surviving line traces to a candidate fact, this raises
   `UnattestedGenerationError` rather than returning a husk of headings as
   a finished resume.
5. `AtsSafetyValidator` checks the finished text and `ResumeStructureParser`
   reads it back as sections, then `ResumePdfRendererPort` renders the file.
6. `ApplicationDocumentArchive` stores that finished text verbatim as an
   immutable snapshot, before anything is returned.

Steps 1 and 3 only delete or transliterate characters, so neither can
introduce a claim the guard rejected or never saw.

Every export is derived from that one guarded text
--------------------------------------------------
The plain-text export *is* the guarded text; the structured export is that
text parsed; the PDF is that text rendered. None of the three is assembled
independently, so they cannot disagree about what the candidate claims — and
since the text is the artifact the provenance guard cleared, a disagreement
would mean a file asserting something unvalidated. It also means there is no
route that renders a PDF from caller-supplied text: a "just export this
string" endpoint would hand anyone a way around the guard entirely.

The stored snapshot is that same text again
-------------------------------------------
Archiving happens here, in the flow that produced the document, rather than
in a "save this resume" use case a caller invokes afterwards. That is the
same argument as the exports: text that arrives from a caller has not been
through the guard, so a store that accepted it would be a way around the
guard *and* a way to misrepresent what was sent. Because the archive is fed
the identical `content` value the exports are built from, the stored
snapshot cannot drift from what the candidate received. It is also not
optional — the use case cannot be constructed without an archive — so no
wiring mistake can produce a resume that was handed out but never recorded
(see `ApplicationDocument` for why anything downstream needs the sent text
rather than a regenerated one).

It is the last step for the symmetric reason: a resume whose PDF failed to
render was never handed to the candidate, and a snapshot of it would claim
otherwise. Nothing incomplete gets recorded, and nothing recorded is
incomplete.

The ATS check is reported, not re-fixed. `AtsSafeTextFormatter` has already
enforced the same rules, so a violation here means enforcement has a gap.
Quietly correcting it a second time would hide that gap forever, so it is
logged as the engineering signal it is and returned to the caller.
"""

from __future__ import annotations

import logging

from src.application.dtos.generation_dtos import (
    AtsSafetyViolationOutput,
    GenerateTailoredResumeInput,
    GuardedDocumentOutput,
    ProvenanceViolationOutput,
    ResumeExportsOutput,
    ResumeSectionOutput,
    TailoredResumeOutput,
)
from src.application.exceptions import UnattestedGenerationError
from src.application.ports.resume_pdf_renderer_port import ResumePdfRendererPort
from src.application.ports.tailored_resume_generator_port import (
    TailoredResumeGeneratorPort,
)
from src.application.services.application_document_archive import (
    ApplicationDocumentArchive,
)
from src.application.services.generation_guard_audit import GenerationGuardAudit
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.services.ats_safe_text_formatter import AtsSafeTextFormatter
from src.domain.services.ats_safety_validator import AtsSafetyReport, AtsSafetyValidator
from src.domain.services.provenance_guard import ProvenanceGuard
from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.services.resume_structure_parser import ResumeStructureParser
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.job_requirements import JobRequirements

logger = logging.getLogger(__name__)


class GenerateTailoredResume:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        fact_assembler: ProvenanceFactAssembler,
        generator: TailoredResumeGeneratorPort,
        pdf_renderer: ResumePdfRendererPort,
        archive: ApplicationDocumentArchive,
        guard: ProvenanceGuard | None = None,
        classifier: RequirementClassifier | None = None,
        audit: GenerationGuardAudit | None = None,
        formatter: AtsSafeTextFormatter | None = None,
        ats_validator: AtsSafetyValidator | None = None,
        structure_parser: ResumeStructureParser | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._fact_assembler = fact_assembler
        self._generator = generator
        self._pdf_renderer = pdf_renderer
        self._archive = archive
        self._guard = guard or ProvenanceGuard()
        self._classifier = classifier or RequirementClassifier()
        self._audit = audit or GenerationGuardAudit()
        self._formatter = formatter or AtsSafeTextFormatter()
        self._ats_validator = ats_validator or AtsSafetyValidator()
        self._structure_parser = structure_parser or ResumeStructureParser()

    async def execute(self, dto: GenerateTailoredResumeInput) -> TailoredResumeOutput:
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
            self._formatter.normalize_plain_text(draft),
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
        if not guarded.has_attested_content:
            raise UnattestedGenerationError(
                document_kind=GeneratedDocumentKind.TAILORED_RESUME.value,
                unsupported_terms=guarded.unsupported_terms,
            )

        content = self._formatter.drop_empty_sections(guarded.content)

        ats_report = self._ats_validator.validate(content)
        self._log_ats_findings(
            report=ats_report, user_id=dto.user_id, job_posting_id=posting.id
        )
        # Exports first, archive second: a resume whose PDF could not be
        # rendered was never handed to the candidate, and a snapshot of it
        # would claim otherwise. Since every export derives from `content`,
        # archiving that same value after the fact stores the identical text.
        exports = self._build_exports(
            content, title=f"Resume - {posting.title} - {posting.company}"
        )
        snapshot = await self._archive.store(
            user_id=dto.user_id,
            job_posting_id=posting.id,
            document_kind=GeneratedDocumentKind.TAILORED_RESUME,
            content=content,
            backing_sources=guarded.backing_sources,
        )

        return TailoredResumeOutput(
            document=GuardedDocumentOutput(
                document_id=snapshot.id,
                job_posting_id=posting.id,
                document_kind=GeneratedDocumentKind.TAILORED_RESUME.value,
                content=content,
                version=snapshot.version,
                backing_sources=[source.value for source in guarded.backing_sources],
                violations=[
                    ProvenanceViolationOutput(
                        line=violation.line,
                        unsupported_terms=list(violation.unsupported_terms),
                    )
                    for violation in guarded.violations
                ],
            ),
            exports=exports,
            ats_safety_violations=[
                AtsSafetyViolationOutput(
                    rule=violation.rule,
                    detail=violation.detail,
                    line=violation.line,
                    line_number=violation.line_number,
                )
                for violation in ats_report.violations
            ],
        )

    def _build_exports(self, content: str, *, title: str) -> ResumeExportsOutput:
        """Derive all three artifacts from the one guarded text."""
        structure = self._structure_parser.parse(content)
        return ResumeExportsOutput(
            text=content,
            pdf=self._pdf_renderer.render(content, title=title),
            contact_lines=list(structure.contact_lines),
            sections=[
                ResumeSectionOutput(heading=section.heading, lines=list(section.lines))
                for section in structure.sections
            ],
        )

    @staticmethod
    def _log_ats_findings(
        *, report: AtsSafetyReport, user_id: str, job_posting_id: str
    ) -> None:
        """A finding means the formatter let something through, so it is
        logged as a defect rather than passed over. The offending line is
        included because the rule name alone doesn't say what to fix."""
        if report.is_safe:
            logger.debug(
                "ats safety check passed for tailored_resume user=%s job=%s",
                user_id,
                job_posting_id,
            )
            return

        logger.warning(
            "ats safety check found %d issue(s) in tailored_resume for user=%s "
            "job=%s; broken rules: %s",
            len(report.violations),
            user_id,
            job_posting_id,
            ",".join(report.broken_rules),
        )
        for violation in report.violations:
            logger.warning(
                "ats safety violation [%s] at line %d: %r",
                violation.rule,
                violation.line_number,
                violation.line,
            )
