"""Celery task — a thin adapter that invokes IngestAggregatorJobs.

Contains NO business logic; it only wires dependencies (Adzuna client,
repository, id generator, and — when configured — the search-API listing
resolver) and runs the use case. Intended to be run on-demand or from a
periodic (celery beat) schedule to keep `job_postings` populated from
Adzuna searches.
"""

from __future__ import annotations

import asyncio
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos.job_ingestion_dtos import IngestAggregatorJobsInput
from src.application.ports.listing_resolver_port import ListingResolverPort
from src.application.use_cases.ingest_aggregator_jobs import IngestAggregatorJobs
from src.infrastructure.config import Settings, get_settings
from src.infrastructure.job_aggregators.adzuna_client import AdzunaJobAggregatorClient
from src.infrastructure.persistence.database import async_session_factory
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.persistence.resolved_listing_repository_impl import (
    SqlAlchemyResolvedListingRepository,
)
from src.infrastructure.search.brave_search_client import BraveSearchClient
from src.infrastructure.search.daily_search_quota import DailySearchQuota
from src.infrastructure.search.search_api_listing_resolver import (
    SearchApiListingResolver,
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


def _build_listing_resolver(
    settings: Settings, session: AsyncSession
) -> ListingResolverPort | None:
    """Wire up the search-API listing resolver, or None when SEARCH_API_KEY
    isn't configured — ingestion still runs, it just skips any listing
    still missing an apply_url/description after this returns None."""
    if not settings.search_api_key.get_secret_value():
        return None
    redis_client = redis.from_url(settings.redis_url)
    return SearchApiListingResolver(
        cache=SqlAlchemyResolvedListingRepository(session),
        quota=DailySearchQuota(redis_client, settings.search_api_daily_quota),
        search_client=BraveSearchClient(settings),
    )


async def _run_ingestion(
    keywords: str, location: str | None, max_pages: int
) -> dict[str, int]:
    settings = get_settings()
    async with async_session_factory() as session:
        repository = SqlAlchemyJobPostingRepository(session)
        aggregator = AdzunaJobAggregatorClient(settings)
        listing_resolver = _build_listing_resolver(settings, session)
        use_case = IngestAggregatorJobs(
            repository=repository,
            aggregator=aggregator,
            id_generator=UuidIdGenerator(),
            listing_resolver=listing_resolver,
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
            "skipped_unresolved_count": result.skipped_unresolved_count,
        }
