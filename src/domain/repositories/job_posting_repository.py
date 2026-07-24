"""JobPostingRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. The domain and application layers depend only
on this abstraction, never on a specific database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.entities.job_posting import JobPosting


class JobPostingRepository(ABC):
    """Persistence contract for `JobPosting` records."""

    @abstractmethod
    async def add(self, job_posting: JobPosting) -> None:
        """Persist a newly normalized job posting."""

    @abstractmethod
    async def update(self, job_posting: JobPosting) -> None:
        """Persist changes to an already-persisted posting — status,
        `last_checked_at`, `consecutive_link_failures` — made via its
        behavior methods (see `JobPosting.mark_stale_if_expired` /
        `apply_link_check`)."""

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

    @abstractmethod
    async def list_due_for_staleness_check(
        self, *, as_of: datetime, recheck_after_days: int, batch_size: int
    ) -> list[JobPosting]:
        """Return up to `batch_size` ACTIVE postings whose `apply_url` is
        due a reachability check — never checked, or last checked more
        than `recheck_after_days` before `as_of` — never-checked and
        oldest-checked first, so a bounded periodic sweep eventually
        covers every posting without re-hitting the same ones every run."""

    @abstractmethod
    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        """Return up to `limit` ACTIVE postings, most recent first — the
        active job set downstream matching/browsing should read from
        instead of the raw table, so STALE/DEAD_LINK postings are never
        surfaced to a candidate."""

    @abstractmethod
    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        """Return up to `limit` postings that have not yet had Epic 03
        requirement extraction run (`requirements is None`), oldest first —
        the queue a periodic extraction sweep works through so newly
        ingested postings eventually get parsed without re-scanning ones
        already done."""
