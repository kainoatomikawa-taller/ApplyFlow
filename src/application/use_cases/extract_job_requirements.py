"""ExtractJobRequirements use case — parses one job posting's description
into structured requirement attributes via the Epic 00 LLM layer, routed
on the cheap model tier (`LlmTaskType.EXTRACTION`, enforced by
`JobRequirementsExtractorPort`'s implementation), and persists the result
against that posting's own record.

Feeds classification and scoring — nothing here fabricates a requirement
the description doesn't support; anything the extractor couldn't
determine stays `None`/empty on the persisted `JobRequirements` (see that
value object's docstring).
"""

from __future__ import annotations

from src.application.dtos.job_requirements_dtos import (
    ExtractJobRequirementsInput,
    ExtractJobRequirementsOutput,
)
from src.application.mappers.job_requirements_mapper import JobRequirementsMapper
from src.application.ports.job_requirements_extractor_port import (
    JobRequirementsExtractorPort,
)
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository


class ExtractJobRequirements:
    def __init__(
        self,
        repository: JobPostingRepository,
        extractor: JobRequirementsExtractorPort,
    ) -> None:
        self._repository = repository
        self._extractor = extractor

    async def execute(
        self, dto: ExtractJobRequirementsInput
    ) -> ExtractJobRequirementsOutput:
        job_posting = await self._repository.get_by_id(dto.job_posting_id)
        if job_posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        requirements = await self._extractor.extract(job_posting.description)
        job_posting.set_requirements(requirements)
        await self._repository.update(job_posting)

        return ExtractJobRequirementsOutput(
            job_posting_id=job_posting.id,
            requirements=JobRequirementsMapper.to_output(requirements),
        )
