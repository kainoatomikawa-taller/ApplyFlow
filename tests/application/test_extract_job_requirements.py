"""Tests for ExtractJobRequirements — parses a job posting's description
into structured requirements via the extractor port and persists them
against that posting's own record.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.application.dtos.job_requirements_dtos import ExtractJobRequirementsInput
from src.application.ports.job_requirements_extractor_port import (
    JobRequirementsExtractorPort,
)
from src.application.use_cases.extract_job_requirements import (
    ExtractJobRequirements,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.job_requirements import JobRequirements


def _posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "id": "job-1",
        "source": "adzuna",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://acme.example.com/careers/1",
        "description": "5+ years Python, Bachelor's required, remote OK.",
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

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        return next((p for p in self.postings if p.id == job_posting_id), None)

    async def find_duplicate(self, **kwargs: object) -> JobPosting | None:
        return None

    async def list_due_for_staleness_check(
        self, *, as_of: datetime, recheck_after_days: int, batch_size: int
    ) -> list[JobPosting]:
        return []

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        return [p for p in self.postings if p.is_active][:limit]

    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        return [p for p in self.postings if p.requirements is None][:limit]


class FakeExtractor(JobRequirementsExtractorPort):
    def __init__(self, requirements: JobRequirements) -> None:
        self.requirements = requirements
        self.calls: list[str] = []

    async def extract(self, description: str) -> JobRequirements:
        self.calls.append(description)
        return self.requirements


@pytest.mark.asyncio
async def test_extracts_and_persists_requirements_on_the_posting():
    posting = _posting()
    repository = FakeJobPostingRepository([posting])
    requirements = JobRequirements(
        degree_level=DegreeLevel.BACHELORS, min_years_experience=5
    )
    extractor = FakeExtractor(requirements)
    use_case = ExtractJobRequirements(repository=repository, extractor=extractor)

    result = await use_case.execute(
        ExtractJobRequirementsInput(job_posting_id="job-1")
    )

    assert extractor.calls == [posting.description]
    assert posting.requirements is requirements
    assert repository.updated == [posting]
    assert result.job_posting_id == "job-1"
    assert result.requirements.degree_level == "bachelors"
    assert result.requirements.min_years_experience == 5


@pytest.mark.asyncio
async def test_raises_when_job_posting_does_not_exist():
    repository = FakeJobPostingRepository([])
    extractor = FakeExtractor(JobRequirements())
    use_case = ExtractJobRequirements(repository=repository, extractor=extractor)

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(
            ExtractJobRequirementsInput(job_posting_id="missing-job")
        )

    assert extractor.calls == []


@pytest.mark.asyncio
async def test_re_extraction_replaces_prior_requirements():
    posting = _posting()
    posting.set_requirements(JobRequirements(degree_level=DegreeLevel.MASTERS))
    repository = FakeJobPostingRepository([posting])
    new_requirements = JobRequirements(degree_level=DegreeLevel.BACHELORS)
    extractor = FakeExtractor(new_requirements)
    use_case = ExtractJobRequirements(repository=repository, extractor=extractor)

    await use_case.execute(ExtractJobRequirementsInput(job_posting_id="job-1"))

    assert posting.requirements is new_requirements
