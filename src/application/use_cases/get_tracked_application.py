"""GetTrackedApplication use case — one sent application with its full status
history.

The tracker's detail read: where this application stands, when it got there, and
every step it took. Scoped to the requesting candidate for the same reason
`UpdateApplicationStatus` is — the repository is keyed on the application id
alone, so ownership is checked here, and another candidate's id resolves to "not
found" rather than to their application.
"""

from __future__ import annotations

from src.application.dtos.tracked_application_dtos import (
    GetTrackedApplicationInput,
    TrackedApplicationOutput,
)
from src.application.mappers.tracked_application_mapper import (
    TrackedApplicationMapper,
)
from src.application.services.sent_document_resolver import SentDocumentResolver
from src.domain.exceptions import TrackedApplicationNotFoundError
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)


class GetTrackedApplication:
    def __init__(
        self,
        repository: TrackedApplicationRepository,
        document_repository: ApplicationDocumentRepository,
    ) -> None:
        self._repository = repository
        self._documents = document_repository

    async def execute(
        self, dto: GetTrackedApplicationInput
    ) -> TrackedApplicationOutput:
        """Return one of this candidate's applications.

        Raises:
            TrackedApplicationNotFoundError: if no application with this id
                belongs to this candidate.
        """
        application = await self._repository.get_by_id(dto.application_id)
        if application is None or application.user_id != dto.user_id:
            raise TrackedApplicationNotFoundError(dto.application_id)
        resume, cover_letter = await SentDocumentResolver(self._documents).resolve(
            application
        )
        return TrackedApplicationMapper.to_output(
            application, resume=resume, cover_letter=cover_letter
        )
