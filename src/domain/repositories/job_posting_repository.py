"""JobPostingRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. The domain and application layers depend only
on this abstraction, never on a specific database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.job_posting import JobPosting


class JobPostingRepository(ABC):
    """Persistence contract for `JobPosting` records."""

    @abstractmethod
    async def add(self, job_posting: JobPosting) -> None:
        """Persist a newly normalized job posting."""

    @abstractmethod
    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        """Return a job posting by id, or None if it does not exist."""
