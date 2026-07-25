"""ReviseGeneratedDocument use case — stores the candidate's edited version
of a resume or cover letter as the next snapshot for that job.

Why an edit path exists at all
------------------------------
A generated document is a draft the candidate reviews before it goes out
(see the tailoring review UI in `frontend/`). They will fix a phrasing, cut
a line, reorder a section — and the document that gets sent has to be the
one they approved, not the one the model wrote. Without a write path, an
edited resume exists only in a browser tab and nothing downstream (the
tracker, interview prep) can read what was actually sent, which is the
whole premise of `ApplicationDocument`.

Why it is not a hole in the provenance guard
--------------------------------------------
`GenerateTailoredResume` explains why there is no "save this resume"
endpoint that takes caller-supplied text: text arriving from a caller has
not been through `ProvenanceGuard`, so a store that accepted it verbatim
would be a way around the guard. This use case takes caller-supplied text
and *puts it through the same guard*, against the same corpus, with the same
posting context — so what gets stored is post-guard content on exactly the
terms generated content is. The edit is the candidate's; the attestation
rule is not theirs to waive.

That has a visible consequence, and it is the intended one: a candidate who
edits in a claim their record does not back gets that line stripped and
reported back as a violation, the same as a model that invented it. The
guard does not know or care which side of the boundary a sentence came
from — only whether the candidate's own attested facts support it. An edit
that survives with nothing attested left raises
`UnattestedGenerationError`, because storing a husk of headings as the
document that went out would be the same false record the generation flows
refuse to write.

Why it is a new version, never an overwrite
-------------------------------------------
`ApplicationDocument` is immutable and its repository has no `update`; this
use case does not change that. An edit is archived through the same
`ApplicationDocumentArchive` as a generation run, so it lands as version
n+1 with the previous version still readable. The history therefore records
what the model produced *and* what the candidate changed it to, which is
strictly more than an overwrite could say.

No generator is involved
------------------------
This flow never calls an LLM: the text is already written. It borrows
`ProvenanceFactAssembler`, `ProvenanceGuard`, `AtsSafeTextFormatter`,
`GenerationGuardAudit`, and the archive from the generation flows precisely
so an edited document is validated and recorded by the same machinery — but
it is its own use case rather than a branch inside either generator, since
use cases never depend on one another (see `src/application/CLAUDE.md`).
"""

from __future__ import annotations

from src.application.dtos.generation_dtos import (
    GuardedDocumentOutput,
    ProvenanceViolationOutput,
    ReviseGeneratedDocumentInput,
)
from src.application.exceptions import UnattestedGenerationError
from src.application.services.application_document_archive import (
    ApplicationDocumentArchive,
)
from src.application.services.generation_guard_audit import GenerationGuardAudit
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.domain.exceptions import InvalidValueError, JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.services.ats_safe_text_formatter import AtsSafeTextFormatter
from src.domain.services.provenance_guard import ProvenanceGuard
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind


class ReviseGeneratedDocument:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        fact_assembler: ProvenanceFactAssembler,
        archive: ApplicationDocumentArchive,
        guard: ProvenanceGuard | None = None,
        audit: GenerationGuardAudit | None = None,
        formatter: AtsSafeTextFormatter | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._fact_assembler = fact_assembler
        self._archive = archive
        # Same defaults as the generation flows, and injectable for the same
        # reason they are there: nothing wired in from outside can replace
        # the guard with something permissive.
        self._guard = guard or ProvenanceGuard()
        self._audit = audit or GenerationGuardAudit()
        self._formatter = formatter or AtsSafeTextFormatter()

    async def execute(self, dto: ReviseGeneratedDocumentInput) -> GuardedDocumentOutput:
        document_kind = self._resolve_kind(dto.document_kind)

        posting = await self._job_posting_repository.get_by_id(dto.job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        facts = await self._fact_assembler.assemble(dto.user_id)

        guarded = self._guard.enforce(
            self._formatter.normalize_plain_text(dto.content),
            facts=facts,
            context_terms=tuple(
                term
                for term in (posting.title, posting.company, posting.location)
                if term
            ),
        )
        self._audit.record(
            document_kind=document_kind,
            user_id=dto.user_id,
            job_posting_id=posting.id,
            guarded=guarded,
        )
        if not guarded.has_attested_content:
            raise UnattestedGenerationError(
                document_kind=document_kind.value,
                unsupported_terms=guarded.unsupported_terms,
            )

        content = guarded.content
        if document_kind is GeneratedDocumentKind.TAILORED_RESUME:
            # A resume the candidate emptied a section of, or whose only
            # backed line under a heading was just stripped, leaves the
            # heading standing over nothing — the same tidy-up the resume
            # generation flow does, for the same reason. A letter has no
            # headings to hollow out.
            content = self._formatter.drop_empty_sections(content)

        snapshot = await self._archive.store(
            user_id=dto.user_id,
            job_posting_id=posting.id,
            document_kind=document_kind,
            content=content,
            backing_sources=guarded.backing_sources,
        )

        return GuardedDocumentOutput(
            document_id=snapshot.id,
            job_posting_id=posting.id,
            document_kind=document_kind.value,
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
        )

    @staticmethod
    def _resolve_kind(document_kind: str) -> GeneratedDocumentKind:
        try:
            return GeneratedDocumentKind(document_kind)
        except ValueError as exc:
            raise InvalidValueError(
                f"'{document_kind}' is not a kind of generated document."
            ) from exc
