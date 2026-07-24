"""Tests for ListActiveJobPostings — the active job set: postings that
have not been flagged STALE or DEAD_LINK.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.application.use_cases.list_active_job_postings import (
    ListActiveJobPostings,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.link_check_outcome import LinkCheckOutcome


def _posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "id": "job-1",
        "source": "adzuna",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://acme.example.com/careers/1",
        "description": "Build things.",
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


class FakeJobPostingRepository(JobPostingRepository):
    def __init__(self, postings: list[JobPosting]) -> None:
        self.postings = postings

    async def add(self, job_posting: JobPosting) -> None:
        self.postings.append(job_posting)

    async def update(self, job_posting: JobPosting) -> None:
        pass

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        return None

    async def find_duplicate(self, **kwargs: object) -> JobPosting | None:
        return None

    async def list_due_for_staleness_check(self, **kwargs: object) -> list[JobPosting]:
        return []

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        return [p for p in self.postings if p.is_active][:limit]


@pytest.mark.asyncio
async def test_excludes_stale_and_dead_link_postings():
    active = _posting(id="job-active")
    dead_link = _posting(id="job-dead")
    dead_link.apply_link_check(
        LinkCheckOutcome.CONFIRMED_DEAD, checked_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    stale = _posting(id="job-stale", posted_at=date(2020, 1, 1))
    stale.mark_stale_if_expired(
        as_of=datetime(2026, 1, 1, tzinfo=UTC), stale_after_days=45
    )

    repository = FakeJobPostingRepository([active, dead_link, stale])
    use_case = ListActiveJobPostings(repository=repository)

    result = await use_case.execute()

    assert [o.id for o in result] == ["job-active"]
    assert result[0].status == "active"


@pytest.mark.asyncio
async def test_empty_when_nothing_is_active():
    dead_link = _posting(id="job-dead")
    dead_link.apply_link_check(
        LinkCheckOutcome.CONFIRMED_DEAD, checked_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    repository = FakeJobPostingRepository([dead_link])
    use_case = ListActiveJobPostings(repository=repository)

    result = await use_case.execute()

    assert result == []


@pytest.mark.asyncio
async def test_respects_limit():
    postings = [_posting(id=f"job-{i}") for i in range(5)]
    repository = FakeJobPostingRepository(postings)
    use_case = ListActiveJobPostings(repository=repository)

    result = await use_case.execute(limit=2)

    assert len(result) == 2
