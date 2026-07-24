"""Tests for GenerateJobFitRationale — produces a "why this fits"
rationale plus a gap list of unmet soft preferences for one posting
against one profile.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.application.dtos.job_fit_rationale_dtos import (
    GenerateJobFitRationaleInput,
)
from src.application.ports.job_fit_rationale_generator_port import (
    JobFitRationaleGeneratorPort,
)
from src.application.use_cases.generate_job_fit_rationale import (
    GenerateJobFitRationale,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.work_authorization import WorkAuthorization
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
        "description": "Build things.",
    }
    defaults.update(overrides)
    return JobPosting(**defaults)


def _profile(**overrides: object) -> UserProfile:
    defaults: dict[str, object] = {
        "id": "profile-1",
        "user_id": "user-1",
        "full_name": "Jane Doe",
        "email": EmailAddress("jane@example.com"),
        "contact_source": ProvenanceSource.USER_ENTERED,
    }
    defaults.update(overrides)
    return UserProfile(**defaults)


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

    async def list_due_for_staleness_check(self, **kwargs: object) -> list[JobPosting]:
        return []

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        return [p for p in self.postings if p.is_active][:limit]

    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        return [p for p in self.postings if p.requirements is None][:limit]


class FakeProfileRepository(ProfileRepository):
    def __init__(self, profiles: list[UserProfile]) -> None:
        self.profiles = profiles

    async def add(self, profile: UserProfile) -> None:
        self.profiles.append(profile)

    async def get_by_id(self, profile_id: str) -> UserProfile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        return next((p for p in self.profiles if p.user_id == user_id), None)

    async def update(self, profile: UserProfile) -> None:
        pass

    async def delete(self, profile_id: str) -> None:
        self.profiles = [p for p in self.profiles if p.id != profile_id]


class FakeGenerator(JobFitRationaleGeneratorPort):
    def __init__(
        self, rationale: str = "This role lines up well with your background."
    ) -> None:
        self.rationale = rationale
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        matched: tuple[str, ...],
        gaps: tuple[str, ...],
    ) -> str:
        self.calls.append(
            {
                "job_title": job_title,
                "company": company,
                "matched": matched,
                "gaps": gaps,
            }
        )
        return self.rationale


@pytest.mark.asyncio
async def test_generates_rationale_grounded_in_met_hard_and_soft_requirements():
    posting = _posting()
    posting.set_requirements(
        JobRequirements(
            work_authorization=WorkAuthorizationStatus.CITIZEN,  # hard, treated as met
            remote_type=RemoteType.HYBRID,
            required_skills=("Python",),
        )
    )
    profile = _profile(
        skills=[Skill(id="s1", name="Python", source=ProvenanceSource.USER_ENTERED)],
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            source=ProvenanceSource.USER_ENTERED,
        ),
    )
    generator = FakeGenerator()
    use_case = GenerateJobFitRationale(
        job_posting_repository=FakeJobPostingRepository([posting]),
        profile_repository=FakeProfileRepository([profile]),
        generator=generator,
    )

    result = await use_case.execute(
        GenerateJobFitRationaleInput(
            job_posting_id="job-1", profile_id="profile-1", as_of=date(2026, 1, 1)
        )
    )

    assert result.job_posting_id == "job-1"
    assert result.rationale == generator.rationale
    assert result.gaps == []
    call = generator.calls[0]
    assert call["job_title"] == "Backend Engineer"
    assert call["company"] == "Acme Corp"
    assert "Python" in call["matched"]
    assert any("citizen" in item.lower() for item in call["matched"])
    assert call["gaps"] == ()


@pytest.mark.asyncio
async def test_unmet_soft_preferences_populate_the_gap_list():
    posting = _posting()
    posting.set_requirements(
        JobRequirements(
            degree_level=DegreeLevel.MASTERS,
            degree_required=False,
            required_skills=("Kubernetes",),
        )
    )
    profile = _profile()  # no degree, no skills on file
    generator = FakeGenerator()
    use_case = GenerateJobFitRationale(
        job_posting_repository=FakeJobPostingRepository([posting]),
        profile_repository=FakeProfileRepository([profile]),
        generator=generator,
    )

    result = await use_case.execute(
        GenerateJobFitRationaleInput(
            job_posting_id="job-1", profile_id="profile-1", as_of=date(2026, 1, 1)
        )
    )

    assert result.gaps == ["Kubernetes"]
    assert generator.calls[0]["gaps"] == ("Kubernetes",)


@pytest.mark.asyncio
async def test_postings_with_no_extracted_requirements_still_generate_a_rationale():
    posting = _posting()
    profile = _profile()
    generator = FakeGenerator()
    use_case = GenerateJobFitRationale(
        job_posting_repository=FakeJobPostingRepository([posting]),
        profile_repository=FakeProfileRepository([profile]),
        generator=generator,
    )

    result = await use_case.execute(
        GenerateJobFitRationaleInput(
            job_posting_id="job-1", profile_id="profile-1", as_of=date(2026, 1, 1)
        )
    )

    assert result.gaps == []
    assert generator.calls[0]["matched"] == ()
    assert generator.calls[0]["gaps"] == ()


@pytest.mark.asyncio
async def test_raises_when_job_posting_does_not_exist():
    use_case = GenerateJobFitRationale(
        job_posting_repository=FakeJobPostingRepository([]),
        profile_repository=FakeProfileRepository([_profile()]),
        generator=FakeGenerator(),
    )

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(
            GenerateJobFitRationaleInput(
                job_posting_id="missing-job",
                profile_id="profile-1",
                as_of=date(2026, 1, 1),
            )
        )


@pytest.mark.asyncio
async def test_raises_when_profile_does_not_exist():
    use_case = GenerateJobFitRationale(
        job_posting_repository=FakeJobPostingRepository([_posting()]),
        profile_repository=FakeProfileRepository([]),
        generator=FakeGenerator(),
    )

    with pytest.raises(ProfileNotFoundError):
        await use_case.execute(
            GenerateJobFitRationaleInput(
                job_posting_id="job-1",
                profile_id="missing-profile",
                as_of=date(2026, 1, 1),
            )
        )
