"""ListJobMatchFeedback use case — a candidate's own feedback history."""

from __future__ import annotations

from src.application.dtos.job_match_feedback_dtos import JobMatchFeedbackOutput
from src.application.mappers.job_match_feedback_mapper import JobMatchFeedbackMapper
from src.domain.repositories.job_match_feedback_repository import (
    JobMatchFeedbackRepository,
)


class ListJobMatchFeedback:
    def __init__(self, repository: JobMatchFeedbackRepository) -> None:
        self._repository = repository

    async def execute(
        self, user_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedbackOutput]:
        feedback = await self._repository.list_by_user_id(user_id, limit=limit)
        return [JobMatchFeedbackMapper.to_output(entry) for entry in feedback]
