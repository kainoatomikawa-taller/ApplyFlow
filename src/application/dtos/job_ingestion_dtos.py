"""DTOs for the job-aggregator ingestion use case."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestAggregatorJobsInput:
    """Search parameters for one ingestion run."""

    keywords: str
    location: str | None = None
    max_pages: int = 1


@dataclass(frozen=True)
class IngestAggregatorJobsOutput:
    """Outcome of one ingestion run."""

    pages_fetched: int
    listings_seen: int
    ingested_count: int
    skipped_duplicate_count: int
