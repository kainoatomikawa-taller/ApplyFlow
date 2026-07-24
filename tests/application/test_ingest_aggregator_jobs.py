"""Tests for IngestAggregatorJobs — fetches aggregator listings and
persists them as normalized JobPosting records.

No network calls: `JobAggregatorPort` and `JobPostingRepository` are
replaced with in-memory fakes, so these run offline and deterministically
while proving the pagination loop, id/source assignment, and
dedup-by-normalized-key behavior.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.application.dtos.job_ingestion_dtos import IngestAggregatorJobsInput
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.ports.job_aggregator_port import (
    AggregatorJobListing,
    AggregatorPage,
    JobAggregatorPort,
)
from src.application.use_cases.ingest_aggregator_jobs import IngestAggregatorJobs
from src.domain.entities.job_posting import JobPosting
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.salary_range import SalaryPeriod, SalaryRange


def _listing(**overrides: object) -> AggregatorJobListing:
    defaults: dict[str, object] = {
        "external_id": "1",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://jobs.example.com/1",
        "description": "Build things.",
        "is_remote": False,
        "location": "NYC",
        "salary": SalaryRange(
            currency="USD", period=SalaryPeriod.YEARLY, min_amount=100_000
        ),
        "posted_at": date(2026, 7, 1),
    }
    defaults.update(overrides)
    return AggregatorJobListing(**defaults)


class FakeIdGenerator(IdGeneratorPort):
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n}"


class FakeJobAggregator(JobAggregatorPort):
    def __init__(self, pages: list[AggregatorPage], source: str = "adzuna") -> None:
        self._pages = pages
        self._source = source
        self.calls: list[tuple[str, str | None, int]] = []

    @property
    def source_name(self) -> str:
        return self._source

    async def fetch_page(
        self, *, keywords: str, location: str | None, page: int
    ) -> AggregatorPage:
        self.calls.append((keywords, location, page))
        index = page - 1
        if index >= len(self._pages):
            return AggregatorPage(listings=[], has_more=False)
        return self._pages[index]


class FakeJobPostingRepository(JobPostingRepository):
    def __init__(self) -> None:
        self.saved: list[JobPosting] = []

    async def add(self, job_posting: JobPosting) -> None:
        self.saved.append(job_posting)

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        return next((j for j in self.saved if j.id == job_posting_id), None)

    async def find_duplicate(
        self,
        *,
        source: str,
        normalized_company: str,
        normalized_title: str,
        normalized_location: str | None,
    ) -> JobPosting | None:
        return next(
            (
                j
                for j in self.saved
                if j.source == source
                and j.normalized_company == normalized_company
                and j.normalized_title == normalized_title
                and j.normalized_location == normalized_location
            ),
            None,
        )


@pytest.mark.asyncio
async def test_ingests_a_single_page_and_persists_normalized_records():
    aggregator = FakeJobAggregator(
        [AggregatorPage(listings=[_listing()], has_more=False)]
    )
    repository = FakeJobPostingRepository()
    use_case = IngestAggregatorJobs(
        repository=repository, aggregator=aggregator, id_generator=FakeIdGenerator()
    )

    result = await use_case.execute(
        IngestAggregatorJobsInput(keywords="engineer", max_pages=5)
    )

    assert result.pages_fetched == 1
    assert result.listings_seen == 1
    assert result.ingested_count == 1
    assert result.skipped_duplicate_count == 0
    assert len(repository.saved) == 1
    saved = repository.saved[0]
    assert saved.id == "id-1"
    assert saved.source == "adzuna"
    assert saved.company == "Acme Corp"
    assert saved.title == "Backend Engineer"
    assert saved.salary is not None
    assert saved.salary.min_amount == 100_000


@pytest.mark.asyncio
async def test_stops_when_aggregator_reports_no_more_pages():
    aggregator = FakeJobAggregator(
        [
            AggregatorPage(listings=[_listing(external_id="1")], has_more=True),
            AggregatorPage(listings=[_listing(external_id="2")], has_more=False),
        ]
    )
    repository = FakeJobPostingRepository()
    use_case = IngestAggregatorJobs(
        repository=repository, aggregator=aggregator, id_generator=FakeIdGenerator()
    )

    result = await use_case.execute(
        IngestAggregatorJobsInput(keywords="engineer", max_pages=10)
    )

    assert result.pages_fetched == 2
    assert aggregator.calls == [("engineer", None, 1), ("engineer", None, 2)]


@pytest.mark.asyncio
async def test_stops_at_max_pages_even_if_more_are_available():
    aggregator = FakeJobAggregator(
        [
            AggregatorPage(listings=[_listing(external_id="1")], has_more=True),
            AggregatorPage(listings=[_listing(external_id="2")], has_more=True),
            AggregatorPage(listings=[_listing(external_id="3")], has_more=True),
        ]
    )
    repository = FakeJobPostingRepository()
    use_case = IngestAggregatorJobs(
        repository=repository, aggregator=aggregator, id_generator=FakeIdGenerator()
    )

    result = await use_case.execute(
        IngestAggregatorJobsInput(keywords="engineer", max_pages=2)
    )

    assert result.pages_fetched == 2
    assert len(aggregator.calls) == 2


@pytest.mark.asyncio
async def test_forwards_keywords_and_location_to_the_aggregator():
    aggregator = FakeJobAggregator([AggregatorPage(listings=[], has_more=False)])
    repository = FakeJobPostingRepository()
    use_case = IngestAggregatorJobs(
        repository=repository, aggregator=aggregator, id_generator=FakeIdGenerator()
    )

    await use_case.execute(
        IngestAggregatorJobsInput(keywords="engineer", location="Remote", max_pages=1)
    )

    assert aggregator.calls == [("engineer", "Remote", 1)]


@pytest.mark.asyncio
async def test_a_listing_already_persisted_is_skipped_not_duplicated():
    existing = JobPosting(
        id="existing-1",
        source="adzuna",
        company="Acme Corp",
        title="Backend Engineer",
        apply_url="https://jobs.example.com/existing",
        description="Already ingested.",
        location="NYC",
    )
    repository = FakeJobPostingRepository()
    repository.saved.append(existing)

    aggregator = FakeJobAggregator(
        [AggregatorPage(listings=[_listing()], has_more=False)]
    )
    use_case = IngestAggregatorJobs(
        repository=repository, aggregator=aggregator, id_generator=FakeIdGenerator()
    )

    result = await use_case.execute(
        IngestAggregatorJobsInput(keywords="engineer", max_pages=1)
    )

    assert result.ingested_count == 0
    assert result.skipped_duplicate_count == 1
    assert len(repository.saved) == 1  # nothing new added


@pytest.mark.asyncio
async def test_distinct_listings_on_the_same_page_are_both_ingested():
    aggregator = FakeJobAggregator(
        [
            AggregatorPage(
                listings=[
                    _listing(external_id="1", title="Backend Engineer"),
                    _listing(external_id="2", title="Frontend Engineer"),
                ],
                has_more=False,
            )
        ]
    )
    repository = FakeJobPostingRepository()
    use_case = IngestAggregatorJobs(
        repository=repository, aggregator=aggregator, id_generator=FakeIdGenerator()
    )

    result = await use_case.execute(
        IngestAggregatorJobsInput(keywords="engineer", max_pages=1)
    )

    assert result.ingested_count == 2
    assert {j.title for j in repository.saved} == {
        "Backend Engineer",
        "Frontend Engineer",
    }
