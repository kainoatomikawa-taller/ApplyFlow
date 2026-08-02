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
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)


class ListApplicationsForJob:
    def __init__(self, repository: TrackedApplicationRepository) -> None:
        self._repository = repository

    async def execute(
        self, dto: ListApplicationsForJobInput
    ) -> list[TrackedApplicationOutput]:
        """Return this candidate's applications to one posting, newest first."""
        applications = await self._repository.list_for_job(
            user_id=dto.user_id, job_posting_id=dto.job_posting_id
        )
        return [
            TrackedApplicationMapper.to_output(application)
            for application in applications
        ]
