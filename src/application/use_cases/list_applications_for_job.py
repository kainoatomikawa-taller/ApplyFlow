"""ListApplicationsForJob use case — every application this candidate sent to
one posting.

Normally one. Two when they applied again months later, which is two real
applications with their own dates, documents, and outcomes — see the repository
interface on why there is no uniqueness constraint on (user, posting). A view
that showed only the latest would quietly lose the first attempt's history,
which is exactly the record someone preparing for a second attempt wants.
"""

from __future__ import annotations

from src.application.dtos.tracked_application_dtos import (
    ListApplicationsForJobInput,
    TrackedApplicationOutput,
)
from src.application.mappers.tracked_application_mapper import (
    TrackedApplicationMapper,
)
from src.application.services.sent_document_resolver import SentDocumentResolver
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)


class ListApplicationsForJob:
    def __init__(
        self,
        repository: TrackedApplicationRepository,
        document_repository: ApplicationDocumentRepository,
    ) -> None:
        self._repository = repository
        self._documents = document_repository

    async def execute(
        self, dto: ListApplicationsForJobInput
    ) -> list[TrackedApplicationOutput]:
        """Return this candidate's applications to one posting, newest first."""
        applications = await self._repository.list_for_job(
            user_id=dto.user_id, job_posting_id=dto.job_posting_id
        )
        # Re-applying to one posting means several rows referencing the same
        # snapshots, so one resolver across the list reads each document once.
        resolver = SentDocumentResolver(self._documents)
        outputs: list[TrackedApplicationOutput] = []
        for application in applications:
            resume, cover_letter = await resolver.resolve(application)
            outputs.append(
                TrackedApplicationMapper.to_output(
                    application, resume=resume, cover_letter=cover_letter
                )
            )
        return outputs
