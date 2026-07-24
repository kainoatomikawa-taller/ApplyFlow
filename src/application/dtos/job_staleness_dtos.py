"""DTOs for the stale-posting / dead-apply-link detection use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.entities.job_posting import JobPosting


@dataclass(frozen=True)
class DetectStaleJobPostingsInput:
    """Parameters for one sweep pass. `as_of` is supplied by the caller
    (rather than read from the clock inside the use case) so a sweep is
    deterministic and testable."""

    as_of: datetime
    batch_size: int = 200
    stale_after_days: int = JobPosting.DEFAULT_STALE_AFTER_DAYS
    recheck_after_days: int = 3
    dead_link_after_failures: int = JobPosting.DEFAULT_DEAD_LINK_FAILURE_THRESHOLD


@dataclass(frozen=True)
class DetectStaleJobPostingsOutput:
    """Outcome of one sweep pass."""

    checked_count: int
    newly_stale_count: int
    newly_dead_link_count: int
    failed_count: int = 0
