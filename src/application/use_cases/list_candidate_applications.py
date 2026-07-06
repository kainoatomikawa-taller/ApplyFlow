"""ListCandidateApplications use case — returns a candidate's applications
ranked by priority using a pure domain service.
"""

from __future__ import annotations

from src.application.dtos.job_application_dtos import JobApplicationOutput
from src.application.mappers.job_application_mapper import JobApplicationMapper
from src.domain.repositories.job_application_repository import (
    JobApplicationRepository,
)
from src.domain.services.application_ranking_service import (
    ApplicationRankingService,
)


class ListCandidateApplications:
    def __init__(
        self,
        repository: JobApplicationRepository,
        ranking_service: ApplicationRankingService,
    ) -> None:
        self._repository = repository
        self._ranking_service = ranking_service

    async def execute(self, candidate_email: str) -> list[JobApplicationOutput]:
        applications = await self._repository.list_by_candidate(candidate_email)
        ranked = self._ranking_service.rank(applications)
        return [JobApplicationMapper.to_output(a) for a in ranked]
