"""Tests for DetectStaleJobPostings — sweeps ACTIVE postings, flagging
ones too old as STALE and probing the rest's apply_url for DEAD_LINK.

`JobPostingRepository` and `ApplyUrlCheckerPort` are both replaced with
in-memory fakes, so these run offline and prove: age-based staleness,
link-check-based dead-link flagging (including the consecutive-failure
threshold for ambiguous outcomes), that a stale-by-age posting skips its
network check entirely, and that one posting's unexpected failure never
sinks the rest of the batch.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.application.dtos.job_staleness_dtos import DetectStaleJobPostingsInput
from src.application.ports.apply_url_checker_port import ApplyUrlCheckerPort
from src.application.use_cases.detect_stale_job_postings import (
    DetectStaleJobPostings,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.job_posting_status import JobPostingStatus
from src.domain.value_objects.link_check_outcome import LinkCheckOutcome


def _posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "id": "job-1",
        "source": "adzuna",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://acme.example.com/careers/1",
        "description": "Build things.",
        "posted_at": date(2026, 7, 1),
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


class FakeJobPostingRepository(JobPostingRepository):
    def __init__(self, postings: list[JobPosting]) -> None:
        self.postings = postings
        self.updated: list[JobPosting] = []

    async def add(self, job_posting: JobPosting) -> None:
        self.postings.append(job_posting)

    async def update(self, job_posting: JobPosting) -> None:
        self.updated.append(job_posting)
        for index, existing in enumerate(self.postings):
            if existing.id == job_posting.id:
                self.postings[index] = job_posting

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        return next((p for p in self.postings if p.id == job_posting_id), None)

    async def find_duplicate(self, **kwargs: object) -> JobPosting | None:
        return None

    async def list_due_for_staleness_check(
        self, *, as_of: datetime, recheck_after_days: int, batch_size: int
    ) -> list[JobPosting]:
        cutoff = as_of - timedelta(days=recheck_after_days)
        due = [
            p
            for p in self.postings
            if p.is_active
            and (p.last_checked_at is None or p.last_checked_at <= cutoff)
        ]
        return due[:batch_size]

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        return [p for p in self.postings if p.is_active][:limit]

    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        return [p for p in self.postings if p.requirements is None][:limit]


class FakeUrlChecker(ApplyUrlCheckerPort):
    def __init__(
        self,
        outcome: LinkCheckOutcome = LinkCheckOutcome.REACHABLE,
        error: Exception | None = None,
    ) -> None:
        self._outcome = outcome
        self._error = error
        self.checked_urls: list[str] = []

    async def check(self, url: str) -> LinkCheckOutcome:
        self.checked_urls.append(url)
        if self._error is not None:
            raise self._error
        return self._outcome


def _dto(**overrides: object) -> DetectStaleJobPostingsInput:
    defaults: dict[str, object] = {
        "as_of": datetime(2026, 7, 24, tzinfo=UTC),
        "batch_size": 10,
        "stale_after_days": 45,
        "recheck_after_days": 3,
        "dead_link_after_failures": 3,
    }
    defaults.update(overrides)
    return DetectStaleJobPostingsInput(**defaults)


@pytest.mark.asyncio
async def test_posting_older_than_threshold_is_flagged_stale_without_a_link_check():
    posting = _posting(posted_at=date(2026, 1, 1))
    repository = FakeJobPostingRepository([posting])
    checker = FakeUrlChecker()
    use_case = DetectStaleJobPostings(repository=repository, url_checker=checker)

    result = await use_case.execute(_dto())

    assert result.checked_count == 1
    assert result.newly_stale_count == 1
    assert result.newly_dead_link_count == 0
    assert repository.postings[0].status == JobPostingStatus.STALE
    # Already excluded by age -- no need to also spend a network request.
    assert checker.checked_urls == []


@pytest.mark.asyncio
async def test_reachable_link_leaves_posting_active():
    posting = _posting()
    repository = FakeJobPostingRepository([posting])
    checker = FakeUrlChecker(outcome=LinkCheckOutcome.REACHABLE)
    use_case = DetectStaleJobPostings(repository=repository, url_checker=checker)

    result = await use_case.execute(_dto())

    assert result.checked_count == 1
    assert result.newly_stale_count == 0
    assert result.newly_dead_link_count == 0
    assert repository.postings[0].status == JobPostingStatus.ACTIVE
    assert checker.checked_urls == [posting.apply_url]


@pytest.mark.asyncio
async def test_confirmed_dead_link_flags_dead_link():
    posting = _posting()
    repository = FakeJobPostingRepository([posting])
    checker = FakeUrlChecker(outcome=LinkCheckOutcome.CONFIRMED_DEAD)
    use_case = DetectStaleJobPostings(repository=repository, url_checker=checker)

    result = await use_case.execute(_dto())

    assert result.newly_dead_link_count == 1
    assert repository.postings[0].status == JobPostingStatus.DEAD_LINK


@pytest.mark.asyncio
async def test_transient_failure_only_flags_dead_link_after_repeated_sweeps():
    posting = _posting()
    repository = FakeJobPostingRepository([posting])
    checker = FakeUrlChecker(outcome=LinkCheckOutcome.TRANSIENT_FAILURE)
    use_case = DetectStaleJobPostings(repository=repository, url_checker=checker)

    # Sweep passes 1 and 2: still ambiguous, must not flag yet.
    for _ in range(2):
        repository.postings[0].last_checked_at = None  # force "due" again
        await use_case.execute(_dto())
    assert repository.postings[0].status == JobPostingStatus.ACTIVE

    # Third consecutive failure crosses the threshold.
    repository.postings[0].last_checked_at = None
    result = await use_case.execute(_dto())

    assert result.newly_dead_link_count == 1
    assert repository.postings[0].status == JobPostingStatus.DEAD_LINK


@pytest.mark.asyncio
async def test_only_due_postings_are_swept():
    recently_checked = _posting(
        id="job-recent", last_checked_at=datetime(2026, 7, 23, tzinfo=UTC)
    )
    never_checked = _posting(id="job-new")
    repository = FakeJobPostingRepository([recently_checked, never_checked])
    checker = FakeUrlChecker()
    use_case = DetectStaleJobPostings(repository=repository, url_checker=checker)

    result = await use_case.execute(_dto(recheck_after_days=3))

    assert result.checked_count == 1
    assert checker.checked_urls == [never_checked.apply_url]


@pytest.mark.asyncio
async def test_one_postings_unexpected_failure_does_not_sink_the_batch():
    ok_posting = _posting(id="job-ok")
    broken_posting = _posting(id="job-broken")
    repository = FakeJobPostingRepository([broken_posting, ok_posting])
    checker = FakeUrlChecker(error=RuntimeError("boom"))
    use_case = DetectStaleJobPostings(repository=repository, url_checker=checker)

    result = await use_case.execute(_dto())

    assert result.failed_count == 2
    assert result.checked_count == 0


@pytest.mark.asyncio
async def test_partial_failure_still_processes_the_healthy_postings():
    class FlakyChecker(ApplyUrlCheckerPort):
        def __init__(self) -> None:
            self.calls = 0

        async def check(self, url: str) -> LinkCheckOutcome:
            self.calls += 1
            if url.endswith("broken"):
                raise RuntimeError("boom")
            return LinkCheckOutcome.REACHABLE

    ok_posting = _posting(id="job-ok", apply_url="https://acme.example.com/ok")
    broken_posting = _posting(
        id="job-broken", apply_url="https://acme.example.com/broken"
    )
    repository = FakeJobPostingRepository([broken_posting, ok_posting])
    checker = FlakyChecker()
    use_case = DetectStaleJobPostings(repository=repository, url_checker=checker)

    result = await use_case.execute(_dto())

    assert result.failed_count == 1
    assert result.checked_count == 1
    assert checker.calls == 2
