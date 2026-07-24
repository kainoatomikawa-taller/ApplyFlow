"""ListActiveJobPostings use case — the active job set: postings that
have not been flagged STALE or DEAD_LINK, so downstream matching/browsing
never surfaces a job the candidate can't actually apply to.
"""

from __future__ import annotations

from src.application.dtos.job_posting_dtos import JobPostingOutput
from src.application.mappers.job_posting_mapper import JobPostingMapper
from src.domain.repositories.job_posting_repository import JobPostingRepository


class ListActiveJobPostings:
    def __init__(self, repository: JobPostingRepository) -> None:
        self._repository = repository

    async def execute(self, limit: int = 100) -> list[JobPostingOutput]:
        postings = await self._repository.list_active(limit=limit)
        return [JobPostingMapper.to_output(p) for p in postings]
