"""SubmitJobApplication use case — moves a DRAFT application to APPLIED."""

from __future__ import annotations

from src.application.dtos.job_application_dtos import JobApplicationOutput
from src.application.mappers.job_application_mapper import JobApplicationMapper
from src.domain.exceptions import ApplicationNotFoundError
from src.domain.repositories.job_application_repository import (
    JobApplicationRepository,
)


class SubmitJobApplication:
    def __init__(self, repository: JobApplicationRepository) -> None:
        self._repository = repository

    async def execute(self, application_id: str) -> JobApplicationOutput:
        application = await self._repository.get_by_id(application_id)
        if application is None:
            raise ApplicationNotFoundError(application_id)

        application.submit()  # business rule enforced inside the entity
        await self._repository.update(application)
        return JobApplicationMapper.to_output(application)
