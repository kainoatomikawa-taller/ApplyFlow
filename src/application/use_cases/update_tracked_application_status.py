"""UpdateTrackedApplicationStatus use case — following a sent application
through its lifecycle.

This is the one write the tracker offers, and it is the reason
`TrackedApplicationRepository` has an `update` at all while the document store
deliberately has none: what was sent is a fact and cannot change, while what
became of it is exactly what a tracker is for.

What this use case does *not* decide
------------------------------------
Which transitions are legal. That is `ApplicationStatus`'s state machine,
reached through `TrackedApplication.change_status`, so the tracker and every
other reader reach the same conclusion about whether a rejected application
can go back to interviewing. A rule restated here would be a second answer to
a question that already has one.

Nor does it touch the documents. `change_status` moves the status and stamps
`updated_at`; the references to what went out are not writable from here, and
`TrackedApplication` refuses to repoint one even when asked.

Scoped to the owner, and a stranger's row is simply absent
-----------------------------------------------------------
`get_by_id` is keyed on the application, not on the candidate, so the
ownership check happens here. Another candidate's application raises the same
`TrackedApplicationNotFoundError` as an id that never existed — the API must
not confirm that an id it was handed is real, and "not yours" would.

Status changes are the candidate's own observation
--------------------------------------------------
Nothing infers them. An interview invitation arrives in the candidate's inbox,
not in ApplyFlow, and a tracker that guessed at outcomes would state things
about an employer's decision that nobody told it. Suppression does not consult
status either (see `AppliedJobIndex`), so moving a row to `rejected` records
what happened without quietly putting the role back into the matched list.
"""

from __future__ import annotations

import logging

from src.application.dtos.tracked_application_dtos import (
    TrackedApplicationOutput,
    UpdateTrackedApplicationStatusInput,
)
from src.application.mappers.tracked_application_mapper import (
    TrackedApplicationMapper,
)
from src.domain.exceptions import (
    InvalidValueError,
    TrackedApplicationNotFoundError,
)
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)
from src.domain.value_objects.application_status import ApplicationStatus

logger = logging.getLogger(__name__)


class UpdateTrackedApplicationStatus:
    def __init__(
        self,
        tracked_application_repository: TrackedApplicationRepository,
        document_repository: ApplicationDocumentRepository,
    ) -> None:
        self._applications = tracked_application_repository
        self._documents = document_repository

    async def execute(
        self, dto: UpdateTrackedApplicationStatusInput
    ) -> TrackedApplicationOutput:
        """Move the application to `dto.status` and return the updated row.

        Returns the whole record rather than an acknowledgement, so the screen
        that made the change re-renders from what was stored — including the
        next set of `allowed_next_statuses`, which the transition just changed.

        Raises:
            InvalidValueError: if `status` is not an application status, or is
                `draft` — a sent application cannot become a draft again, and
                `TrackedApplication` refuses to hold one.
            TrackedApplicationNotFoundError: if no such application belongs to
                this candidate.
            BusinessRuleViolationError: if the transition is not one
                `ApplicationStatus` allows.
        """
        try:
            target = ApplicationStatus(dto.status)
        except ValueError as exc:
            allowed = ", ".join(status.value for status in ApplicationStatus)
            raise InvalidValueError(
                f"'{dto.status}' is not an application status. Expected one "
                f"of: {allowed}."
            ) from exc

        application = await self._applications.get_by_id(dto.application_id)
        if application is None or application.user_id != dto.user_id:
            # Deliberately one error for both: see the module docstring.
            raise TrackedApplicationNotFoundError(dto.application_id)

        previous = application.status
        # The domain owns the rule; a refusal surfaces as
        # BusinessRuleViolationError and nothing is written.
        application.change_status(target)
        await self._applications.update(application)
        logger.info(
            "application=%s moved from %s to %s",
            application.id,
            previous.value,
            application.status.value,
        )

        resume = await self._documents.get_by_id(application.resume_document_id)
        cover_letter = (
            await self._documents.get_by_id(application.cover_letter_document_id)
            if application.cover_letter_document_id is not None
            else None
        )
        return TrackedApplicationMapper.to_output(
            application, resume=resume, cover_letter=cover_letter
        )
