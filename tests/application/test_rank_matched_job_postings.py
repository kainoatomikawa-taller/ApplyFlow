"""Tests for RankMatchedJobPostings — the final ranked job list: filtered
for hard disqualifiers, ordered by fit score, each entry carrying its
score, rationale, and gap list.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.application.dtos.ranked_job_dtos import RankMatchedJobsInput
from src.application.exceptions import ExternalServiceError
from src.application.ports.job_fit_rationale_generator_port import (
    JobFitRationaleGeneratorPort,
)
from src.application.use_cases.rank_matched_job_postings import (
    RankMatchedJobPostings,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)

_AS_OF = date(2026, 1, 1)


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
        self, rationale: str = "Good fit.", error: Exception | None = None
    ) -> None:
        self.rationale = rationale
        self.error = error
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
        if self.error is not None:
            raise self.error
        return self.rationale


def _use_case(
    postings: list[JobPosting],
    profiles: list[UserProfile],
    generator: JobFitRationaleGeneratorPort | None = None,
) -> RankMatchedJobPostings:
    return RankMatchedJobPostings(
        job_posting_repository=FakeJobPostingRepository(postings),
        profile_repository=FakeProfileRepository(profiles),
        rationale_generator=generator or FakeGenerator(),
    )


@pytest.mark.asyncio
async def test_hard_disqualified_postings_are_excluded():
    disqualifying = _posting(id="job-citizens-only")
    disqualifying.set_requirements(
        JobRequirements(work_authorization=WorkAuthorizationStatus.CITIZEN)
    )
    ok = _posting(id="job-open", description="No restrictions.")

    profile = _profile(
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.VISA_HOLDER,
            source=ProvenanceSource.USER_ENTERED,
        )
    )
    use_case = _use_case([disqualifying, ok], [profile])

    result = await use_case.execute(
        RankMatchedJobsInput(user_id="user-1", as_of=_AS_OF)
    )

    assert [entry.job_posting.id for entry in result] == ["job-open"]


@pytest.mark.asyncio
async def test_results_are_ordered_by_fit_score_descending():
    weak = _posting(id="job-weak")
    weak.set_requirements(JobRequirements(required_skills=("Python", "Go", "Rust")))
    strong = _posting(id="job-strong")
    strong.set_requirements(JobRequirements(required_skills=("Python",)))

    profile = _profile(
        skills=[Skill(id="s1", name="Python", source=ProvenanceSource.USER_ENTERED)]
    )
    use_case = _use_case([weak, strong], [profile])

    result = await use_case.execute(
        RankMatchedJobsInput(user_id="user-1", as_of=_AS_OF)
    )

    assert [entry.job_posting.id for entry in result] == ["job-strong", "job-weak"]
    assert result[0].score > result[1].score


@pytest.mark.asyncio
async def test_each_entry_carries_score_rationale_and_gaps():
    posting = _posting()
    posting.set_requirements(JobRequirements(required_skills=("Python", "Kubernetes")))
    profile = _profile(
        skills=[Skill(id="s1", name="Python", source=ProvenanceSource.USER_ENTERED)]
    )
    generator = FakeGenerator(rationale="Strong Python background.")
    use_case = _use_case([posting], [profile], generator)

    result = await use_case.execute(
        RankMatchedJobsInput(user_id="user-1", as_of=_AS_OF)
    )

    assert len(result) == 1
    entry = result[0]
    assert entry.score == 50
    assert entry.rationale == "Strong Python background."
    assert entry.gaps == ["Kubernetes"]
    assert generator.calls[0]["matched"] == ("Python",)
    assert generator.calls[0]["gaps"] == ("Kubernetes",)


@pytest.mark.asyncio
async def test_rationale_generation_failure_falls_back_instead_of_dropping_the_job():
    posting = _posting()
    posting.set_requirements(JobRequirements(required_skills=("Python",)))
    profile = _profile(
        skills=[Skill(id="s1", name="Python", source=ProvenanceSource.USER_ENTERED)]
    )
    generator = FakeGenerator(error=ExternalServiceError("LLM is down"))
    use_case = _use_case([posting], [profile], generator)

    result = await use_case.execute(
        RankMatchedJobsInput(user_id="user-1", as_of=_AS_OF)
    )

    assert len(result) == 1
    assert "Python" in result[0].rationale


@pytest.mark.asyncio
async def test_postings_with_no_extracted_requirements_are_included_and_score_100():
    posting = _posting()
    profile = _profile()
    use_case = _use_case([posting], [profile])

    result = await use_case.execute(
        RankMatchedJobsInput(user_id="user-1", as_of=_AS_OF)
    )

    assert len(result) == 1
    assert result[0].score == 100
    assert result[0].gaps == []


@pytest.mark.asyncio
async def test_raises_when_profile_does_not_exist_for_user():
    use_case = _use_case([_posting()], [])

    with pytest.raises(ProfileNotFoundError):
        await use_case.execute(
            RankMatchedJobsInput(user_id="missing-user", as_of=_AS_OF)
        )


@pytest.mark.asyncio
async def test_respects_limit_on_the_active_job_set():
    postings = [_posting(id=f"job-{i}") for i in range(5)]
    profile = _profile()
    use_case = _use_case(postings, [profile])

    result = await use_case.execute(
        RankMatchedJobsInput(user_id="user-1", as_of=_AS_OF, limit=2)
    )

    assert len(result) == 2
