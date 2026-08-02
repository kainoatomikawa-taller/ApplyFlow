"""Mapper between TrackedApplication and its output DTOs.

Takes the resolved document snapshots as arguments rather than fetching them:
a mapper that could reach a repository would be a use case, and the resolution
is the caller's job precisely so a list read can batch it (see
`ListTrackedApplications`).

`user_id` is never mapped out. Every read is already scoped to the requesting
candidate, so echoing it back would only widen what a response carries.
`submission_key` is not mapped out either — it is the idempotency key for the
submission event, useful only to the flow that writes the row, and a value a
client never needs is a value a client should not be handed.
"""

from __future__ import annotations

from src.application.dtos.tracked_application_dtos import (
    SentDocumentOutput,
    TrackedApplicationOutput,
)
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.tracked_application import TrackedApplication


class TrackedApplicationMapper:
    """Translates tracked applications into output DTOs."""

    @staticmethod
    def to_sent_document_output(
        document: ApplicationDocument,
    ) -> SentDocumentOutput:
        return SentDocumentOutput(
            id=document.id,
            document_kind=document.document_kind.value,
            version=document.version,
            content_sha256=document.content_sha256,
            created_at=document.created_at,
        )

    @staticmethod
    def to_output(
        application: TrackedApplication,
        *,
        resume: ApplicationDocument | None = None,
        cover_letter: ApplicationDocument | None = None,
    ) -> TrackedApplicationOutput:
        to_sent = TrackedApplicationMapper.to_sent_document_output
        return TrackedApplicationOutput(
            id=application.id,
            job_posting_id=application.job_posting_id,
            company_name=application.company_name,
            role_title=application.role_title,
            job_location=application.job_location,
            applied_at=application.applied_at,
            status=application.status.value,
            is_open=application.is_open,
            allowed_next_statuses=[
                status.value for status in application.status.allowed_transitions
            ],
            resume=to_sent(resume) if resume is not None else None,
            cover_letter=to_sent(cover_letter) if cover_letter is not None else None,
            created_at=application.created_at,
            updated_at=application.updated_at,
        )
