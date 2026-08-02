"""Mapper between TrackedApplication and its output DTOs.

Takes the resolved document snapshots as arguments rather than fetching them: a
mapper that could reach a repository would be a use case, and the resolution is
the caller's job precisely so a list read can batch it (see
`SentDocumentResolver`).
"""

from __future__ import annotations

from src.application.dtos.tracked_application_dtos import (
    ApplicationStatusChangeOutput,
    SentDocumentOutput,
    TrackedApplicationOutput,
)
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.value_objects.application_status_change import ApplicationStatusChange


class TrackedApplicationMapper:
    """Translates tracked applications into output DTOs.

    `user_id` and `submission_key` are never mapped out. Every read is already
    scoped to the requesting user, so echoing the id back would only widen what
    a response carries; and the submission key is an internal idempotency
    handle, not something a client should learn to depend on.

    `is_open` and `current_status_since` are copied from the entity rather than
    recomputed here. Both are domain answers — one reads
    `ApplicationStatus.is_terminal`, the other the last history entry — and a
    mapper that derived them itself would be a second implementation free to
    disagree with the first.
    """

    @staticmethod
    def to_sent_document_output(document: ApplicationDocument) -> SentDocumentOutput:
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
        """Map one application, optionally with the snapshots its references
        resolve to.

        The snapshots are optional so a caller that only needs the row does not
        have to fetch them, and so a reference that no longer resolves comes
        back as an absent document rather than as a failed read — see the DTO
        module docstring.
        """
        to_sent = TrackedApplicationMapper.to_sent_document_output
        return TrackedApplicationOutput(
            id=application.id,
            job_posting_id=application.job_posting_id,
            company_name=application.company_name,
            role_title=application.role_title,
            applied_at=application.applied_at,
            status=application.status.value,
            is_open=application.is_open,
            current_status_since=application.current_status_since,
            resume_document_id=application.resume_document_id,
            cover_letter_document_id=application.cover_letter_document_id,
            job_location=application.job_location,
            allowed_next_statuses=[
                status.value for status in application.status.allowed_transitions
            ],
            resume=to_sent(resume) if resume is not None else None,
            cover_letter=to_sent(cover_letter) if cover_letter is not None else None,
            status_history=[
                TrackedApplicationMapper.to_status_change_output(change)
                for change in application.status_history
            ],
            created_at=application.created_at,
            updated_at=application.updated_at,
        )

    @staticmethod
    def to_status_change_output(
        change: ApplicationStatusChange,
    ) -> ApplicationStatusChangeOutput:
        return ApplicationStatusChangeOutput(
            status=change.status.value,
            changed_at=change.changed_at,
            previous_status=(
                change.previous_status.value
                if change.previous_status is not None
                else None
            ),
            note=change.note,
        )
