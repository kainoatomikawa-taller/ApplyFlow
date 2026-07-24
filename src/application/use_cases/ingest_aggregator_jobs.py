"""IngestAggregatorJobs use case — fetch job listings from an aggregator
source and persist them as normalized `JobPosting` records.

Works against any `JobAggregatorPort` implementation (Adzuna today, other
aggregators later) — this use case never knows which source answered the
call, only how to walk its pages and normalize what comes back. A listing
already represented on this source (same normalized company/title/location
— see `JobPosting`) is skipped rather than re-inserted, so re-running an
ingestion (retried pages, a scheduled re-poll) never creates duplicate
rows.

`JobPosting` requires a non-empty `apply_url` and `description`, but not
every aggregator listing has both. When one is missing and a
`ListingResolverPort` was supplied, this use case asks it to fill in the
gap (a search-API lookup, cached and quota-limited entirely inside that
port — see its docstring); if the listing is still missing a required
field afterward (no resolver configured, no confident match, quota
exhausted), it is skipped rather than raising, so one company's
unresolvable listing never aborts the rest of the run.
"""

from __future__ import annotations

from src.application.dtos.job_ingestion_dtos import (
    IngestAggregatorJobsInput,
    IngestAggregatorJobsOutput,
)
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.ports.job_aggregator_port import JobAggregatorPort
from src.application.ports.listing_resolver_port import ListingResolverPort
from src.domain.entities.job_posting import JobPosting
from src.domain.repositories.job_posting_repository import JobPostingRepository


class IngestAggregatorJobs:
    def __init__(
        self,
        repository: JobPostingRepository,
        aggregator: JobAggregatorPort,
        id_generator: IdGeneratorPort,
        listing_resolver: ListingResolverPort | None = None,
    ) -> None:
        self._repository = repository
        self._aggregator = aggregator
        self._id_generator = id_generator
        self._listing_resolver = listing_resolver

    async def execute(
        self, dto: IngestAggregatorJobsInput
    ) -> IngestAggregatorJobsOutput:
        pages_fetched = 0
        listings_seen = 0
        ingested_count = 0
        skipped_duplicate_count = 0
        skipped_unresolved_count = 0

        page_number = 1
        while page_number <= dto.max_pages:
            page = await self._aggregator.fetch_page(
                keywords=dto.keywords, location=dto.location, page=page_number
            )
            pages_fetched += 1

            for listing in page.listings:
                listings_seen += 1

                apply_url = listing.apply_url
                description = listing.description
                is_missing_fields = not apply_url.strip() or not description.strip()
                if is_missing_fields and self._listing_resolver is not None:
                    resolved = await self._listing_resolver.resolve(
                        company=listing.company, title=listing.title
                    )
                    if resolved is not None:
                        apply_url = apply_url.strip() or resolved.apply_url
                        description = description.strip() or resolved.description

                if not apply_url.strip() or not description.strip():
                    skipped_unresolved_count += 1
                    continue

                job_posting = JobPosting(
                    id=self._id_generator.new_id(),
                    source=self._aggregator.source_name,
                    company=listing.company,
                    title=listing.title,
                    apply_url=apply_url,
                    description=description,
                    is_remote=listing.is_remote,
                    location=listing.location,
                    salary=listing.salary,
                    posted_at=listing.posted_at,
                )

                duplicate = await self._repository.find_duplicate(
                    source=job_posting.source,
                    normalized_company=job_posting.normalized_company,
                    normalized_title=job_posting.normalized_title,
                    normalized_location=job_posting.normalized_location,
                )
                if duplicate is not None:
                    skipped_duplicate_count += 1
                    continue

                await self._repository.add(job_posting)
                ingested_count += 1

            if not page.has_more:
                break
            page_number += 1

        return IngestAggregatorJobsOutput(
            pages_fetched=pages_fetched,
            listings_seen=listings_seen,
            ingested_count=ingested_count,
            skipped_duplicate_count=skipped_duplicate_count,
            skipped_unresolved_count=skipped_unresolved_count,
        )
