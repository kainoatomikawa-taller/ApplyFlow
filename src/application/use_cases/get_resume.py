"""GetResume use case — fetch a single resume's metadata and extracted text.

Scoped to the requesting user: a resume belonging to someone else is
reported as not found rather than forbidden, so the endpoint never
confirms or denies another user's resume ids exist.
"""

from __future__ import annotations

from src.application.dtos.resume_dtos import ResumeOutput
from src.application.mappers.resume_mapper import ResumeMapper
from src.domain.exceptions import ResumeNotFoundError
from src.domain.repositories.resume_repository import ResumeRepository


class GetResume:
    def __init__(self, repository: ResumeRepository) -> None:
        self._repository = repository

    async def execute(self, resume_id: str, user_id: str) -> ResumeOutput:
        resume = await self._repository.get_by_id(resume_id)
        if resume is None or resume.user_id != user_id:
            raise ResumeNotFoundError(resume_id)
        return ResumeMapper.to_output(resume)
