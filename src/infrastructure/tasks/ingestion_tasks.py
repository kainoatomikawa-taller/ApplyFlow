"""Celery task — a thin adapter that invokes IngestAggregatorJobs.

Contains NO business logic; it only wires dependencies (Adzuna client,
repository, id generator) and runs the use case. Intended to be run
on-demand or from a periodic (celery beat) schedule to keep `job_postings`
populated from Adzuna searches.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.application.dtos.job_ingestion_dtos import IngestAggregatorJobsInput
from src.application.use_cases.ingest_aggregator_jobs import IngestAggregatorJobs
from src.infrastructure.config import get_settings
from src.infrastructure.job_aggregators.adzuna_client import AdzunaJobAggregatorClient
from src.infrastructure.persistence.database import async_session_factory
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.services.uuid_id_generator import UuidIdGenerator
from src.infrastructure.tasks.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    name="applyflow.ingest_adzuna_jobs", bind=True, max_retries=3
)
def ingest_adzuna_jobs_task(
    self: Any,
    keywords: str,
    location: str | None = None,
    max_pages: int = 1,
) -> dict[str, int]:
    """Run the IngestAggregatorJobs use case, sourced from Adzuna, as a
    background job."""
    try:
        return asyncio.run(_run_ingestion(keywords, location, max_pages))
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30) from exc


async def _run_ingestion(
    keywords: str, location: str | None, max_pages: int
) -> dict[str, int]:
    settings = get_settings()
    async with async_session_factory() as session:
        repository = SqlAlchemyJobPostingRepository(session)
        aggregator = AdzunaJobAggregatorClient(settings)
        use_case = IngestAggregatorJobs(
            repository=repository,
            aggregator=aggregator,
            id_generator=UuidIdGenerator(),
        )
        result = await use_case.execute(
            IngestAggregatorJobsInput(
                keywords=keywords, location=location, max_pages=max_pages
            )
        )
        return {
            "pages_fetched": result.pages_fetched,
            "listings_seen": result.listings_seen,
            "ingested_count": result.ingested_count,
            "skipped_duplicate_count": result.skipped_duplicate_count,
        }
