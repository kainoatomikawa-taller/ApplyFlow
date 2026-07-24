"""Tests for ClassifyJobRequirements — loads a job posting's parsed
requirements and splits them into hard disqualifiers vs soft preferences.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.application.dtos.requirement_classification_dtos import (
    ClassifyJobRequirementsInput,
)
from src.application.use_cases.classify_job_requirements import (
    ClassifyJobRequirements,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)


def _posting(**overrides: object) -> JobPosting:
    defaults: dict[str, object] = {
        "id": "job-1",
        "source": "adzuna",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "apply_url": "https://acme.example.com/careers/1",
        "description": "Bachelor's required, 5+ years Python preferred.",
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


@pytest.mark.asyncio
async def test_classifies_a_postings_persisted_requirements():
    posting = _posting()
    posting.set_requirements(
        JobRequirements(
            degree_level=DegreeLevel.BACHELORS,
            degree_required=True,
            remote_type=RemoteType.ON_SITE,
            locations=("Washington, DC",),
            work_authorization=WorkAuthorizationStatus.CITIZEN,
            min_years_experience=5,
            required_skills=("Python",),
        )
    )
    repository = FakeJobPostingRepository([posting])
    use_case = ClassifyJobRequirements(repository=repository)

    result = await use_case.execute(
        ClassifyJobRequirementsInput(job_posting_id="job-1")
    )

    assert result.job_posting_id == "job-1"
    assert {item.category for item in result.hard} == {
        "degree",
        "location",
        "work_authorization",
    }
    assert {item.category for item in result.soft} == {"experience", "skill"}


@pytest.mark.asyncio
async def test_posting_with_no_extracted_requirements_yields_empty_classification():
    posting = _posting()
    repository = FakeJobPostingRepository([posting])
    use_case = ClassifyJobRequirements(repository=repository)

    result = await use_case.execute(
        ClassifyJobRequirementsInput(job_posting_id="job-1")
    )

    assert result.hard == []
    assert result.soft == []


@pytest.mark.asyncio
async def test_raises_when_job_posting_does_not_exist():
    repository = FakeJobPostingRepository([])
    use_case = ClassifyJobRequirements(repository=repository)

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(
            ClassifyJobRequirementsInput(job_posting_id="missing-job")
        )
