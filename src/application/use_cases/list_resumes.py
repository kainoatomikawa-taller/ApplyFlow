"""ListResumes use case — every resume the requesting user has uploaded."""

from __future__ import annotations

from src.application.dtos.resume_dtos import ResumeOutput
from src.application.mappers.resume_mapper import ResumeMapper
from src.domain.repositories.resume_repository import ResumeRepository


class ListResumes:
    def __init__(self, repository: ResumeRepository) -> None:
        self._repository = repository

    async def execute(self, user_id: str) -> list[ResumeOutput]:
        resumes = await self._repository.list_by_user_id(user_id)
        return [ResumeMapper.to_output(r) for r in resumes]
