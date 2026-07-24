"""ParseResume use case tests using in-memory fakes for the ports/repositories.

Covers the acceptance criteria for "Implement LLM resume parsing to
structured JSON": parsed facts land on the profile tagged
`parsed_resume`, and messy/incomplete resumes degrade gracefully instead
of fabricating data or crashing.
"""

from datetime import date

import pytest

from src.application.dtos.resume_dtos import UploadResumeInput
from src.application.ports.resume_parser_port import (
    ParsedEducationEntry,
    ParsedResumeData,
    ParsedSkill,
    ParsedWorkHistoryEntry,
    ResumeParserPort,
)
from src.application.use_cases.parse_resume import ParseResume
from src.application.use_cases.upload_resume import UploadResume
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import ProfileMissingContactInfoError, ResumeNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.repositories.resume_repository import ResumeRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.domain.value_objects.provenance_source import ProvenanceSource
from tests.application.test_resume_use_cases import (
    FakeTextExtractor,
    InMemoryFileStorage,
    InMemoryResumeRepo,
    SequentialIdGenerator,
)


class InMemoryProfileRepo(ProfileRepository):
    def __init__(self) -> None:
        self.store: dict[str, UserProfile] = {}

    async def add(self, profile: UserProfile) -> None:
        self.store[profile.id] = profile

    async def get_by_id(self, profile_id: str) -> UserProfile | None:
        return self.store.get(profile_id)

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        for profile in self.store.values():
            if profile.user_id == user_id:
                return profile
        return None

    async def update(self, profile: UserProfile) -> None:
        self.store[profile.id] = profile

    async def delete(self, profile_id: str) -> None:
        self.store.pop(profile_id, None)


class FakeResumeParser(ResumeParserPort):
    def __init__(self, result: ParsedResumeData) -> None:
        self.result = result
        self.calls: list[str] = []

    async def parse(self, resume_text: str) -> ParsedResumeData:
        self.calls.append(resume_text)
        return self.result


async def _seed_resume(
    resume_repo: ResumeRepository, *, user_id: str = "user-1", text: str = "resume text"
):
    return await UploadResume(
        repository=resume_repo,
        storage=InMemoryFileStorage(),
        text_extractor=FakeTextExtractor(),
        id_generator=SequentialIdGenerator(),
    ).execute(
        UploadResumeInput(
            user_id=user_id,
            original_filename="resume.txt",
            content_type="text/plain",
            content=text.encode("utf-8"),
        )
    )


@pytest.mark.asyncio
async def test_parse_resume_creates_a_new_profile_with_parsed_resume_provenance():
    resume_repo = InMemoryResumeRepo()
    profile_repo = InMemoryProfileRepo()
    uploaded = await _seed_resume(resume_repo)

    parsed = ParsedResumeData(
        full_name="Jane Doe",
        email="jane@example.com",
        phone="555-1234",
        headline="Senior Engineer",
        location="Remote",
        work_history=[
            ParsedWorkHistoryEntry(
                company_name="Acme",
                job_title="Engineer",
                start_date=date(2020, 1, 1),
                end_date=None,
            )
        ],
        education=[
            ParsedEducationEntry(
                institution_name="State University",
                degree="B.S. Computer Science",
            )
        ],
        skills=[ParsedSkill(name="Python", proficiency=ProficiencyLevel.EXPERT)],
    )
    parser = FakeResumeParser(parsed)

    output = await ParseResume(
        resume_repository=resume_repo,
        profile_repository=profile_repo,
        resume_parser=parser,
        id_generator=SequentialIdGenerator(),
    ).execute(uploaded.id, "user-1")

    assert parser.calls == [uploaded.extracted_text]
    assert output.full_name == "Jane Doe"
    assert output.email == "jane@example.com"
    assert output.contact_source == ProvenanceSource.PARSED_RESUME.value
    assert len(output.work_history) == 1
    assert output.work_history[0].company_name == "Acme"
    assert output.work_history[0].source == ProvenanceSource.PARSED_RESUME.value
    assert len(output.education) == 1
    assert output.education[0].source == ProvenanceSource.PARSED_RESUME.value
    assert len(output.skills) == 1
    assert output.skills[0].name == "Python"
    assert output.skills[0].source == ProvenanceSource.PARSED_RESUME.value

    stored = profile_repo.store[output.id]
    assert stored.user_id == "user-1"


@pytest.mark.asyncio
async def test_parse_resume_merges_facts_into_existing_profile_keeps_contact_info():
    resume_repo = InMemoryResumeRepo()
    profile_repo = InMemoryProfileRepo()
    uploaded = await _seed_resume(resume_repo)

    existing = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    await profile_repo.add(existing)

    parsed = ParsedResumeData(
        full_name="Someone Else",  # must NOT overwrite user-entered contact info
        email="someone-else@example.com",
        skills=[ParsedSkill(name="Go")],
    )
    parser = FakeResumeParser(parsed)

    output = await ParseResume(
        resume_repository=resume_repo,
        profile_repository=profile_repo,
        resume_parser=parser,
        id_generator=SequentialIdGenerator(),
    ).execute(uploaded.id, "user-1")

    assert output.id == "profile-1"
    assert output.full_name == "Jane Doe"
    assert output.email == "jane@example.com"
    assert output.contact_source == ProvenanceSource.USER_ENTERED.value
    assert [s.name for s in output.skills] == ["Go"]


@pytest.mark.asyncio
async def test_parse_resume_raises_when_no_contact_info_and_no_existing_profile():
    resume_repo = InMemoryResumeRepo()
    profile_repo = InMemoryProfileRepo()
    uploaded = await _seed_resume(resume_repo)

    parser = FakeResumeParser(ParsedResumeData())  # nothing extracted

    with pytest.raises(ProfileMissingContactInfoError):
        await ParseResume(
            resume_repository=resume_repo,
            profile_repository=profile_repo,
            resume_parser=parser,
            id_generator=SequentialIdGenerator(),
        ).execute(uploaded.id, "user-1")

    assert profile_repo.store == {}


@pytest.mark.asyncio
async def test_parse_resume_skips_work_history_entries_missing_required_fields():
    resume_repo = InMemoryResumeRepo()
    profile_repo = InMemoryProfileRepo()
    uploaded = await _seed_resume(resume_repo)

    parsed = ParsedResumeData(
        full_name="Jane Doe",
        email="jane@example.com",
        work_history=[
            ParsedWorkHistoryEntry(company_name="Acme", job_title="Engineer"),
            ParsedWorkHistoryEntry(
                company_name=None, job_title="Engineer", start_date=date(2020, 1, 1)
            ),
            ParsedWorkHistoryEntry(
                company_name="Acme",
                job_title="Engineer",
                start_date=date(2020, 1, 1),
            ),
        ],
    )
    parser = FakeResumeParser(parsed)

    output = await ParseResume(
        resume_repository=resume_repo,
        profile_repository=profile_repo,
        resume_parser=parser,
        id_generator=SequentialIdGenerator(),
    ).execute(uploaded.id, "user-1")

    # Only the one entry with company_name + job_title + start_date survives.
    assert len(output.work_history) == 1
    assert output.work_history[0].start_date == date(2020, 1, 1)


@pytest.mark.asyncio
async def test_parse_resume_dedupes_skills_case_insensitively():
    resume_repo = InMemoryResumeRepo()
    profile_repo = InMemoryProfileRepo()
    uploaded = await _seed_resume(resume_repo)

    parsed = ParsedResumeData(
        full_name="Jane Doe",
        email="jane@example.com",
        skills=[
            ParsedSkill(name="Python"),
            ParsedSkill(name="python"),
            ParsedSkill(name="  "),
            ParsedSkill(name=None),
        ],
    )
    parser = FakeResumeParser(parsed)

    output = await ParseResume(
        resume_repository=resume_repo,
        profile_repository=profile_repo,
        resume_parser=parser,
        id_generator=SequentialIdGenerator(),
    ).execute(uploaded.id, "user-1")

    assert [s.name for s in output.skills] == ["Python"]


@pytest.mark.asyncio
async def test_parse_resume_skips_skills_already_on_an_existing_profile():
    resume_repo = InMemoryResumeRepo()
    profile_repo = InMemoryProfileRepo()
    uploaded = await _seed_resume(resume_repo)

    existing = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    existing.add_skill(
        Skill(id="sk-existing", name="Python", source=ProvenanceSource.USER_ENTERED)
    )
    await profile_repo.add(existing)

    parsed = ParsedResumeData(
        skills=[ParsedSkill(name="python"), ParsedSkill(name="Go")]
    )
    parser = FakeResumeParser(parsed)

    output = await ParseResume(
        resume_repository=resume_repo,
        profile_repository=profile_repo,
        resume_parser=parser,
        id_generator=SequentialIdGenerator(),
    ).execute(uploaded.id, "user-1")

    names = sorted(s.name for s in output.skills)
    assert names == ["Go", "Python"]


@pytest.mark.asyncio
async def test_parse_resume_raises_not_found_for_someone_elses_resume():
    resume_repo = InMemoryResumeRepo()
    profile_repo = InMemoryProfileRepo()
    uploaded = await _seed_resume(resume_repo, user_id="user-1")

    parser = FakeResumeParser(ParsedResumeData())

    with pytest.raises(ResumeNotFoundError):
        await ParseResume(
            resume_repository=resume_repo,
            profile_repository=profile_repo,
            resume_parser=parser,
            id_generator=SequentialIdGenerator(),
        ).execute(uploaded.id, "someone-else")
