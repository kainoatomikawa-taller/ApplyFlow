"""CreateJobApplication use case.

One class, one `execute(dto)` method. Dependencies (repository, id
generator, task queue) are injected via the constructor as abstractions.
"""

from __future__ import annotations

from src.application.dtos.job_application_dtos import (
    CreateJobApplicationInput,
    JobApplicationOutput,
)
from src.application.mappers.job_application_mapper import JobApplicationMapper
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.job_application import JobApplication
from src.domain.repositories.job_application_repository import (
    JobApplicationRepository,
)
from src.domain.value_objects.email_address import EmailAddress


class CreateJobApplication:
    def __init__(
        self,
        repository: JobApplicationRepository,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._repository = repository
        self._id_generator = id_generator

    async def execute(self, dto: CreateJobApplicationInput) -> JobApplicationOutput:
        application = JobApplication(
            id=self._id_generator.new_id(),
            candidate_email=EmailAddress(dto.candidate_email),
            company_name=dto.company_name,
            role_title=dto.role_title,
            job_description=dto.job_description,
        )
        await self._repository.add(application)
        return JobApplicationMapper.to_output(application)
