"""ListApplicationDocuments use case — what a candidate has had produced,
newest first: every job, or one job's full version history.

Returns summaries without document text. That is what the tracker's list
view needs, and it keeps the system's most PII-dense content out of
responses that don't display it — a caller that wants a document asks for it
by id (`GetApplicationDocument`) or by job and kind
(`GetLatestApplicationDocument`).
"""

from __future__ import annotations

from src.application.dtos.application_document_dtos import (
    ApplicationDocumentSummaryOutput,
    ListApplicationDocumentsInput,
)
from src.application.mappers.application_document_mapper import (
    ApplicationDocumentMapper,
)
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)


class ListApplicationDocuments:
    def __init__(self, repository: ApplicationDocumentRepository) -> None:
        self._repository = repository

    async def execute(
        self, dto: ListApplicationDocumentsInput
    ) -> list[ApplicationDocumentSummaryOutput]:
        if dto.job_posting_id is None:
            documents = await self._repository.list_by_user_id(
                dto.user_id, limit=dto.limit
            )
        else:
            documents = await self._repository.list_for_job(
                user_id=dto.user_id,
                job_posting_id=dto.job_posting_id,
                limit=dto.limit,
            )
        return [
            ApplicationDocumentMapper.to_summary_output(document)
            for document in documents
        ]
