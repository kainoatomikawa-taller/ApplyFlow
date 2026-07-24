"""Real-database smoke test for the job posting persistence layer.

Exercises `SqlAlchemyJobPostingRepository` against an actual Postgres
connection end to end: create -> read by id. Mirrors
`test_resume_persistence_smoke.py`.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.domain.entities.job_posting import JobPosting
from src.domain.value_objects.salary_range import SalaryPeriod, SalaryRange
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


@pytest.mark.asyncio
async def test_create_and_read_round_trip_against_a_real_database(
    schema_ready: None,
) -> None:
    job_posting = JobPosting(
        id=f"smoke-job-{uuid.uuid4()}",
        source="linkedin",
        company="  Acme Corp  ",
        title="Senior Backend Engineer",
        apply_url="https://jobs.example.com/acme/senior-backend-engineer",
        description="Build and operate ApplyFlow's ingestion pipeline.",
        is_remote=True,
        location="Remote - US",
        salary=SalaryRange(
            currency="USD",
            period=SalaryPeriod.YEARLY,
            min_amount=150_000,
            max_amount=190_000,
        ),
        posted_at=date(2026, 7, 20),
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyJobPostingRepository(session)
        await repository.add(job_posting)

        fetched = await repository.get_by_id(job_posting.id)
        assert fetched is not None
        assert fetched.source == "linkedin"
        assert fetched.company == "  Acme Corp  "
        assert fetched.title == "Senior Backend Engineer"
        assert fetched.is_remote is True
        assert fetched.location == "Remote - US"
        assert fetched.apply_url == job_posting.apply_url
        assert fetched.description == job_posting.description
        assert fetched.posted_at == date(2026, 7, 20)
        assert fetched.salary is not None
        assert fetched.salary.currency == "USD"
        assert fetched.salary.period == SalaryPeriod.YEARLY
        assert fetched.salary.min_amount == 150_000
        assert fetched.salary.max_amount == 190_000

        # Dedup key fields are derived automatically, not passed in.
        assert fetched.normalized_company == "acme corp"
        assert fetched.normalized_title == "senior backend engineer"
        assert fetched.normalized_location == "remote - us"

        # Matched by normalized dedup key, not by id — a repeat run of this
        # very test (same hardcoded company/title/location) is itself a
        # legitimate duplicate under that key, so this only asserts that
        # *some* matching record comes back, not this run's specific row.
        duplicate = await repository.find_duplicate(
            source=job_posting.source,
            normalized_company=job_posting.normalized_company,
            normalized_title=job_posting.normalized_title,
            normalized_location=job_posting.normalized_location,
        )
        assert duplicate is not None
        assert duplicate.normalized_company == job_posting.normalized_company
        assert duplicate.normalized_title == job_posting.normalized_title
        assert duplicate.normalized_location == job_posting.normalized_location

        no_match = await repository.find_duplicate(
            source=job_posting.source,
            normalized_company=job_posting.normalized_company,
            normalized_title="a totally different title that has never been used",
            normalized_location=job_posting.normalized_location,
        )
        assert no_match is None
