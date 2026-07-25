"""GetApplicationDocument use case — fetch one stored snapshot, including
the exact text that was produced.

Scoped to the requesting user: a snapshot belonging to someone else is
reported as not found rather than forbidden, so the endpoint never confirms
or denies another candidate's document ids exist (same rule as `GetResume`).
"""

from __future__ import annotations

from src.application.dtos.application_document_dtos import (
    ApplicationDocumentOutput,
    GetApplicationDocumentInput,
)
from src.application.mappers.application_document_mapper import (
    ApplicationDocumentMapper,
)
from src.domain.exceptions import ApplicationDocumentNotFoundError
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)


class GetApplicationDocument:
    def __init__(self, repository: ApplicationDocumentRepository) -> None:
        self._repository = repository

    async def execute(
        self, dto: GetApplicationDocumentInput
    ) -> ApplicationDocumentOutput:
        document = await self._repository.get_by_id(dto.document_id)
        if document is None or document.user_id != dto.user_id:
            raise ApplicationDocumentNotFoundError(dto.document_id)
        return ApplicationDocumentMapper.to_output(document)
