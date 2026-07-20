"""AnalyzeJobApplication use case.

Runs an AI analysis of a resume against the stored job description, then
attaches the resulting match score and cover letter to the application.
"""

from __future__ import annotations

from src.application.dtos.job_application_dtos import (
    AnalyzeApplicationInput,
    JobApplicationOutput,
)
from src.application.mappers.job_application_mapper import JobApplicationMapper
from src.application.ports.resume_analyzer_port import ResumeAnalyzerPort
from src.domain.exceptions import ApplicationNotFoundError
from src.domain.repositories.job_application_repository import (
    JobApplicationRepository,
)
from src.domain.value_objects.match_score import MatchScore


class AnalyzeJobApplication:
    def __init__(
        self,
        repository: JobApplicationRepository,
        analyzer: ResumeAnalyzerPort,
    ) -> None:
        self._repository = repository
        self._analyzer = analyzer

    async def execute(self, dto: AnalyzeApplicationInput) -> JobApplicationOutput:
        application = await self._repository.get_by_id(dto.application_id)
        if application is None:
            raise ApplicationNotFoundError(dto.application_id)

        result = await self._analyzer.analyze(
            resume_text=dto.resume_text,
            job_description=application.job_description,
        )

        application.attach_analysis(
            score=MatchScore(result.match_score),
            cover_letter=result.cover_letter,
        )
        await self._repository.update(application)
        return JobApplicationMapper.to_output(application)
