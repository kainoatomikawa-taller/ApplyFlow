"""GetLatestApplicationDocument use case — the resume or cover letter this
application actually went out with.

This is the reuse path the snapshot store exists for: the tracker and
interview prep ask what was sent for a job and get the stored text back,
instead of paying for a fresh generation that would answer a subtly
different question (see `ApplicationDocument`).

"Latest" is the newest stored version for the (user, job, kind). Earlier
versions remain readable through `ListApplicationDocuments` — they are the
history of what was produced, and the newest is what the most recent
submission carried.

A job with no stored document of that kind raises
`NoStoredApplicationDocumentError` rather than returning None, so a caller
cannot mistake "nothing was ever produced for this job" for an empty
document.
"""

from __future__ import annotations

from src.application.dtos.application_document_dtos import (
    ApplicationDocumentOutput,
    GetLatestApplicationDocumentInput,
)
from src.application.mappers.application_document_mapper import (
    ApplicationDocumentMapper,
)
from src.domain.exceptions import (
    InvalidValueError,
    NoStoredApplicationDocumentError,
)
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind


class GetLatestApplicationDocument:
    def __init__(self, repository: ApplicationDocumentRepository) -> None:
        self._repository = repository

    async def execute(
        self, dto: GetLatestApplicationDocumentInput
    ) -> ApplicationDocumentOutput:
        try:
            document_kind = GeneratedDocumentKind(dto.document_kind)
        except ValueError as exc:
            raise InvalidValueError(
                f"'{dto.document_kind}' is not a kind of generated document."
            ) from exc

        document = await self._repository.get_latest(
            user_id=dto.user_id,
            job_posting_id=dto.job_posting_id,
            document_kind=document_kind,
        )
        if document is None:
            raise NoStoredApplicationDocumentError(
                job_posting_id=dto.job_posting_id,
                document_kind=document_kind.value,
            )
        return ApplicationDocumentMapper.to_output(document)
