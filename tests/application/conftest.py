"""Shared fakes for the provenance-guarded generation use cases.

`GenerateTailoredResume` and `GenerateCoverLetter` take the same
collaborators, so their tests share one set of in-memory doubles rather
than each defining its own — the two flows must stay verifiably identical
about what counts as evidence.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource


class StubJobPostingRepository(JobPostingRepository):
    """Only `get_by_id` is exercised by the generation flows; the rest of
    the contract raises so an accidental extra call is loud."""

    def __init__(self, posting: JobPosting | None) -> None:
        self._posting = posting
        self.requested: list[str] = []

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        self.requested.append(job_posting_id)
        return self._posting

    async def add(self, job_posting: JobPosting) -> None:
        raise NotImplementedError  # pragma: no cover

    async def update(self, job_posting: JobPosting) -> None:
        raise NotImplementedError  # pragma: no cover

    async def find_duplicate(
        self,
        *,
        source: str,
        normalized_company: str,
        normalized_title: str,
        normalized_location: str | None,
    ) -> JobPosting | None:
        raise NotImplementedError  # pragma: no cover

    async def list_due_for_staleness_check(
        self, *, as_of: datetime, recheck_after_days: int, batch_size: int
    ) -> list[JobPosting]:
        raise NotImplementedError  # pragma: no cover

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        raise NotImplementedError  # pragma: no cover

    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        raise NotImplementedError  # pragma: no cover


class StubProfileRepository(ProfileRepository):
    def __init__(self, profile: UserProfile | None) -> None:
        self._profile = profile

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        return self._profile

    async def add(self, profile: UserProfile) -> None:
        raise NotImplementedError  # pragma: no cover

    async def get_by_id(self, profile_id: str) -> UserProfile | None:
        raise NotImplementedError  # pragma: no cover

    async def update(self, profile: UserProfile) -> None:
        raise NotImplementedError  # pragma: no cover

    async def delete(self, profile_id: str) -> None:
        raise NotImplementedError  # pragma: no cover


class StubAnswerMemoryRepository(AnswerMemoryRepository):
    def __init__(self, memories: list[AnswerMemory] | None = None) -> None:
        self._memories = memories or []

    async def list_by_user_id(self, user_id: str) -> list[AnswerMemory]:
        return [m for m in self._memories if m.user_id == user_id]

    async def add(self, answer_memory: AnswerMemory) -> None:
        raise NotImplementedError  # pragma: no cover

    async def get_by_id(self, answer_memory_id: str) -> AnswerMemory | None:
        raise NotImplementedError  # pragma: no cover

    async def delete(self, answer_memory_id: str) -> None:
        raise NotImplementedError  # pragma: no cover


class RecordingGenerator:
    """Stands in for either generator port: returns a scripted draft and
    records what it was asked for, so tests can prove what the use case
    sends to the LLM boundary."""

    def __init__(self, draft: str) -> None:
        self._draft = draft
        self.job_title: str | None = None
        self.company: str | None = None
        self.requirements: tuple[str, ...] = ()
        self.facts: tuple[str, ...] = ()
        # Only the cover-letter port takes highlighted answers; the resume
        # port never passes them, so this stays empty in that flow.
        self.relevant_answers: tuple[str, ...] = ()

    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        facts: tuple[str, ...],
        relevant_answers: tuple[str, ...] = (),
    ) -> str:
        self.job_title = job_title
        self.company = company
        self.requirements = requirements
        self.facts = facts
        self.relevant_answers = relevant_answers
        return self._draft


@pytest.fixture
def profile() -> UserProfile:
    """A candidate with one dated role, its description, and one skill —
    enough real material for a document to be written from."""
    profile = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id="job-1",
            company_name="Acme Corp",
            job_title="Backend Engineer",
            start_date=date(2019, 3, 1),
            end_date=date(2022, 6, 30),
            description="Built payment services in Python.",
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    profile.add_skill(
        Skill(id="skill-1", name="Python", source=ProvenanceSource.PARSED_RESUME)
    )
    return profile


@pytest.fixture
def posting() -> JobPosting:
    """A posting whose requirements go beyond the candidate's record: it
    wants Terraform, which nothing in the profile backs."""
    return JobPosting(
        id="job-posting-1",
        source="greenhouse",
        company="Globex",
        title="Senior Platform Engineer",
        apply_url="https://globex.example.com/jobs/1",
        description="Platform role.",
        location="Austin, TX",
        requirements=JobRequirements(required_skills=("Python", "Terraform")),
    )


@pytest.fixture
def answer_memory() -> AnswerMemory:
    return AnswerMemory(
        id="mem-1",
        user_id="user-1",
        question_text="Have you led a team?",
        answer_text="Yes, I led a team of 5 engineers.",
        embedding=[0.1, 0.2],
        source=ProvenanceSource.ANSWER,
    )


@pytest.fixture
def fact_assembler(profile: UserProfile) -> ProvenanceFactAssembler:
    return ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository(),
    )
