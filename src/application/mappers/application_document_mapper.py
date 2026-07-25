"""Mapper between ApplicationDocument and its output DTOs."""

from __future__ import annotations

from src.application.dtos.application_document_dtos import (
    ApplicationDocumentOutput,
    ApplicationDocumentSummaryOutput,
)
from src.domain.entities.application_document import ApplicationDocument


class ApplicationDocumentMapper:
    """Translates stored snapshots into output DTOs.

    `user_id` is never mapped out: every read is already scoped to the
    requesting user by the use case, so echoing the id back would only
    widen what a response carries.
    """

    @staticmethod
    def to_output(document: ApplicationDocument) -> ApplicationDocumentOutput:
        return ApplicationDocumentOutput(
            id=document.id,
            job_posting_id=document.job_posting_id,
            document_kind=document.document_kind.value,
            version=document.version,
            content=document.content,
            content_sha256=document.content_sha256,
            created_at=document.created_at,
            backing_sources=[source.value for source in document.backing_sources],
        )

    @staticmethod
    def to_summary_output(
        document: ApplicationDocument,
    ) -> ApplicationDocumentSummaryOutput:
        return ApplicationDocumentSummaryOutput(
            id=document.id,
            job_posting_id=document.job_posting_id,
            document_kind=document.document_kind.value,
            version=document.version,
            content_sha256=document.content_sha256,
            created_at=document.created_at,
            backing_sources=[source.value for source in document.backing_sources],
        )
