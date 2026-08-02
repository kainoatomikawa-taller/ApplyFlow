"""Mapper between TrackedApplication and its output DTOs."""

from __future__ import annotations

from src.application.dtos.tracked_application_dtos import (
    ApplicationStatusChangeOutput,
    TrackedApplicationOutput,
)
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
    def to_output(application: TrackedApplication) -> TrackedApplicationOutput:
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
            status_history=[
                TrackedApplicationMapper.to_status_change_output(change)
                for change in application.status_history
            ],
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
