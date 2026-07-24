"""Mapper between the JobPosting entity and its output DTO."""

from __future__ import annotations

from src.application.dtos.job_posting_dtos import JobPostingOutput
from src.domain.entities.job_posting import JobPosting


class JobPostingMapper:
    """Translates domain entities into output DTOs."""

    @staticmethod
    def to_output(job_posting: JobPosting) -> JobPostingOutput:
        return JobPostingOutput(
            id=job_posting.id,
            source=job_posting.source,
            company=job_posting.company,
            title=job_posting.title,
            apply_url=job_posting.apply_url,
            location=job_posting.location,
            is_remote=job_posting.is_remote,
            status=job_posting.status.value,
            posted_at=job_posting.posted_at,
            created_at=job_posting.created_at,
        )
