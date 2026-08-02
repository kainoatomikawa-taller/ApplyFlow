"""UpdateApplicationStatus use case — move one sent application along its
lifecycle and keep the record of the move.

This is the only write path for an application's status. Everything about
*whether* a move is allowed lives in the domain: `ApplicationStatus` owns the
transition rules and `TrackedApplication.change_status` appends the history
entry as it reassigns the status. What is left here is the orchestration —
resolve the string to a status, find the application, ask it to move, save it.

Ownership is checked, not assumed
--------------------------------
The repository's `get_by_id` is keyed on the application id alone, so this use
case verifies the row belongs to the requesting candidate and raises
`TrackedApplicationNotFoundError` when it does not. Deliberately the same error
as a genuinely missing id: distinguishing them would confirm that some other
candidate's application exists under an id someone guessed, and a status update
names an id directly, which makes it the most probeable route in the tracker.

Nothing is regenerated, and nothing is re-sent
--------------------------------------------
A status change records what an employer did — a reply, an invitation, a
rejection. It touches no document and no portal: there is no path from updating
a status to producing a document or contacting anyone.

The document repository it holds is **read-only in practice and by intent** —
it is here so the response can carry the same resolved snapshots a read does,
because the screen that made the change re-renders the row from what came back.
Returning a row with its documents missing would make a status change look like
it had erased what was sent. Resolution goes through `SentDocumentResolver`, so
this path cannot reach `get_latest` and cannot repoint anything.
"""

from __future__ import annotations

import logging

from src.application.dtos.tracked_application_dtos import (
    TrackedApplicationOutput,
    UpdateApplicationStatusInput,
)
from src.application.mappers.tracked_application_mapper import (
    TrackedApplicationMapper,
)
from src.application.services.sent_document_resolver import SentDocumentResolver
from src.domain.exceptions import InvalidValueError, TrackedApplicationNotFoundError
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)
from src.domain.value_objects.application_status import ApplicationStatus

logger = logging.getLogger(__name__)


class UpdateApplicationStatus:
    def __init__(
        self,
        repository: TrackedApplicationRepository,
        document_repository: ApplicationDocumentRepository,
    ) -> None:
        self._repository = repository
        self._documents = document_repository

    async def execute(
        self, dto: UpdateApplicationStatusInput
    ) -> TrackedApplicationOutput:
        """Move the application to `dto.status` and persist the change.

        Raises:
            InvalidValueError: if `dto.status` is not an application status, or
                is `draft` — a status a sent application cannot hold.
            TrackedApplicationNotFoundError: if no application with this id
                belongs to this candidate.
            BusinessRuleViolationError: if the move is not allowed from where
                the application currently stands (raised by the domain).
        """
        target = self._resolve(dto.status)

        application = await self._repository.get_by_id(dto.application_id)
        if application is None or application.user_id != dto.user_id:
            raise TrackedApplicationNotFoundError(dto.application_id)

        # Raises on an illegal transition, before anything is written.
        change = application.change_status(target, note=dto.note)
        await self._repository.update(application)

        # Statuses and ids only. The note is the candidate's own free text and
        # is deliberately left out — see `ApplicationStatusChange.note`.
        logger.info(
            "application=%s moved %s -> %s for user=%s (history now %d entries)",
            application.id,
            change.previous_status.value if change.previous_status else "none",
            change.status.value,
            dto.user_id,
            len(application.status_history),
        )
        resume, cover_letter = await SentDocumentResolver(self._documents).resolve(
            application
        )
        return TrackedApplicationMapper.to_output(
            application, resume=resume, cover_letter=cover_letter
        )

    @staticmethod
    def _resolve(status: str) -> ApplicationStatus:
        try:
            target = ApplicationStatus(status)
        except ValueError as exc:
            allowed = ", ".join(
                candidate.value
                for candidate in ApplicationStatus
                if candidate is not ApplicationStatus.DRAFT
            )
            raise InvalidValueError(
                f"'{status}' is not an application status. Expected one of: "
                f"{allowed}."
            ) from exc
        # Refused here rather than left to the entity so the message can say
        # what to do instead: a draft is an ApplicationReview, and a sent
        # application can never go back to being one.
        if target is ApplicationStatus.DRAFT:
            raise InvalidValueError(
                f"An application that was sent cannot be moved to "
                f"'{ApplicationStatus.DRAFT.value}' — that status belongs to an "
                "application still being prepared, which is an "
                "ApplicationReview."
            )
        return target
