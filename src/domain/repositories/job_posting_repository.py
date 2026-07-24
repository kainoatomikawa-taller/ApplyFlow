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

    @abstractmethod
    async def find_duplicate(
        self,
        *,
        source: str,
        normalized_company: str,
        normalized_title: str,
        normalized_location: str | None,
    ) -> JobPosting | None:
        """Return an already-persisted posting matching this dedup key, or
        None. Ingestion use cases call this before `add` so re-running an
        aggregator fetch (pagination retries, a scheduled re-poll) never
        creates duplicate rows for a posting already ingested from the same
        source."""
