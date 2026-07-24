"""Tests for DetectJobRequirementGaps — checks a job posting's requirements
against a candidate's profile facts and remembered answers, flagging every
requirement neither source backs up.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.application.dtos.requirement_gap_dtos import DetectJobRequirementGapsInput
from src.application.ports.requirement_gap_detector_port import (
    RequirementGapDetectorPort,
)
from src.application.use_cases.detect_job_requirement_gaps import (
    DetectJobRequirementGaps,
)
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource


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


def _answer_memory(question: str, answer: str) -> AnswerMemory:
    return AnswerMemory(
        id=f"mem-{question}",
        user_id="user-1",
        question_text=question,
        answer_text=answer,
        embedding=[0.1, 0.2],
        source=ProvenanceSource.ANSWER,
    )


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


class FakeAnswerMemoryRepository(AnswerMemoryRepository):
    def __init__(self, memories: list[AnswerMemory]) -> None:
        self.memories = memories

    async def add(self, answer_memory: AnswerMemory) -> None:
        self.memories.append(answer_memory)

    async def get_by_id(self, answer_memory_id: str) -> AnswerMemory | None:
        return next((m for m in self.memories if m.id == answer_memory_id), None)

    async def list_by_user_id(self, user_id: str) -> list[AnswerMemory]:
        return [m for m in self.memories if m.user_id == user_id]

    async def delete(self, answer_memory_id: str) -> None:
        self.memories = [m for m in self.memories if m.id != answer_memory_id]


class FakeDetector(RequirementGapDetectorPort):
    def __init__(self, gaps: tuple[str, ...] = ()) -> None:
        self.gaps = gaps
        self.calls: list[dict[str, object]] = []

    async def detect_gaps(
        self,
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        candidate_facts: tuple[str, ...],
    ) -> tuple[str, ...]:
        self.calls.append(
            {
                "job_title": job_title,
                "company": company,
                "requirements": requirements,
                "candidate_facts": candidate_facts,
            }
        )
        return self.gaps


@pytest.mark.asyncio
async def test_passes_requirements_from_the_posting_and_facts_from_profile_and_memory():
    posting = _posting()
    posting.set_requirements(JobRequirements(required_skills=("Kubernetes",)))
    profile = _profile(
        skills=[Skill(id="s1", name="Python", source=ProvenanceSource.USER_ENTERED)]
    )
    memory = _answer_memory(
        "Do you have leadership experience?", "Yes, led a team of 5."
    )
    detector = FakeDetector(gaps=("Kubernetes",))
    use_case = DetectJobRequirementGaps(
        job_posting_repository=FakeJobPostingRepository([posting]),
        profile_repository=FakeProfileRepository([profile]),
        answer_memory_repository=FakeAnswerMemoryRepository([memory]),
        detector=detector,
    )

    result = await use_case.execute(
        DetectJobRequirementGapsInput(
            job_posting_id="job-1", user_id="user-1", as_of=date(2026, 1, 1)
        )
    )

    assert result.job_posting_id == "job-1"
    assert result.gaps == ["Kubernetes"]
    call = detector.calls[0]
    assert call["job_title"] == "Backend Engineer"
    assert call["company"] == "Acme Corp"
    assert "Kubernetes" in call["requirements"]
    assert any("Python" in fact for fact in call["candidate_facts"])
    assert any(
        "leadership experience" in fact and "led a team of 5" in fact
        for fact in call["candidate_facts"]
    )


@pytest.mark.asyncio
async def test_postings_with_no_extracted_requirements_yield_no_gaps():
    posting = _posting()
    profile = _profile()
    detector = FakeDetector()
    use_case = DetectJobRequirementGaps(
        job_posting_repository=FakeJobPostingRepository([posting]),
        profile_repository=FakeProfileRepository([profile]),
        answer_memory_repository=FakeAnswerMemoryRepository([]),
        detector=detector,
    )

    result = await use_case.execute(
        DetectJobRequirementGapsInput(
            job_posting_id="job-1", user_id="user-1", as_of=date(2026, 1, 1)
        )
    )

    assert result.gaps == []
    assert detector.calls[0]["requirements"] == ()


@pytest.mark.asyncio
async def test_raises_when_job_posting_does_not_exist():
    use_case = DetectJobRequirementGaps(
        job_posting_repository=FakeJobPostingRepository([]),
        profile_repository=FakeProfileRepository([_profile()]),
        answer_memory_repository=FakeAnswerMemoryRepository([]),
        detector=FakeDetector(),
    )

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(
            DetectJobRequirementGapsInput(
                job_posting_id="missing-job",
                user_id="user-1",
                as_of=date(2026, 1, 1),
            )
        )


@pytest.mark.asyncio
async def test_raises_when_profile_does_not_exist():
    use_case = DetectJobRequirementGaps(
        job_posting_repository=FakeJobPostingRepository([_posting()]),
        profile_repository=FakeProfileRepository([]),
        answer_memory_repository=FakeAnswerMemoryRepository([]),
        detector=FakeDetector(),
    )

    with pytest.raises(ProfileNotFoundError):
        await use_case.execute(
            DetectJobRequirementGapsInput(
                job_posting_id="job-1",
                user_id="missing-user",
                as_of=date(2026, 1, 1),
            )
        )
