"""ApplicationDocumentArchive — the one place a produced document becomes a
stored snapshot, so both generation flows archive identically.

Why a shared service rather than a step in each use case: `GenerateTailoredResume`
and `GenerateCoverLetter` must not depend on one another (see
`src/application/CLAUDE.md`), and "read the version count, number the next
snapshot, persist it" copied into both is exactly the kind of duplication
that drifts — one flow gaining a version bump the other doesn't, and the
tracker quietly reading two different conventions. The same reasoning already
put `ProvenanceFactAssembler` and `GenerationGuardAudit` here.

What it takes, and what it therefore cannot store
-------------------------------------------------
It takes `backing_sources` from the guard's own result, not from the caller's
judgement, and `ApplicationDocument` refuses a snapshot with none (only
attested content is ever stored as sent). So the archive cannot be handed a
raw model draft and asked to keep it: an unguarded document has no backing
sources to supply. There is deliberately no method here that stores
caller-supplied text under a caller-supplied provenance.

The numbering rule itself lives on the entity (`ApplicationDocument.snapshot`).
This service only supplies the count it reads through the repository, so
there is one definition of what "version 2" means.
"""

from __future__ import annotations

import logging

from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.application_document import ApplicationDocument
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource

logger = logging.getLogger(__name__)


class ApplicationDocumentArchive:
    """Stores the exact content a generation flow produced."""

    def __init__(
        self,
        repository: ApplicationDocumentRepository,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._repository = repository
        self._id_generator = id_generator

    async def store(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
        content: str,
        backing_sources: tuple[ProvenanceSource, ...],
    ) -> ApplicationDocument:
        """Archive `content` verbatim as the next version for this job and
        kind, and return the stored snapshot.

        `content` must be the text the flow is actually returning to its
        caller — archiving anything else would make the store's whole
        premise false.
        """
        stored_versions = await self._repository.count_versions(
            user_id=user_id,
            job_posting_id=job_posting_id,
            document_kind=document_kind,
        )
        document = ApplicationDocument.snapshot(
            document_id=self._id_generator.new_id(),
            user_id=user_id,
            job_posting_id=job_posting_id,
            document_kind=document_kind,
            content=content,
            backing_sources=backing_sources,
            stored_versions=stored_versions,
        )
        await self._repository.add(document)

        # Ids, kind, and version only — the content is sensitive (see
        # `ApplicationDocument`), and its digest is what identifies it.
        logger.info(
            "stored %s v%d for user=%s job=%s as document=%s (sha256=%s)",
            document.document_kind.value,
            document.version,
            user_id,
            job_posting_id,
            document.id,
            document.content_sha256,
        )
        return document
