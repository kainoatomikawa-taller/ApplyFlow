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
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import ProfileMissingContactInfoError, ResumeNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.repositories.resume_repository import ResumeRepository
from src.domain.value_objects.address import Address
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.domain.value_objects.profile_links import ProfileLinks
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


# ---- Re-parsing must not duplicate history ----------------------------------
#
# Parsing is now one of two ways history gets onto a profile, and the two are meant
# to be combinable: type in the jobs a résumé missed, upload the résumé for the
# rest. That makes duplicate-on-merge a user-visible defect rather than a
# theoretical one — and it was already a real one, since parsing appended
# unconditionally and nothing could delete an entry.


def _one_job(
    *,
    company: str = "Acme",
    title: str = "Engineer",
    start: date = date(2020, 1, 1),
) -> ParsedWorkHistoryEntry:
    return ParsedWorkHistoryEntry(
        company_name=company, job_title=title, start_date=start
    )


def _parsed(**overrides) -> ParsedResumeData:
    defaults = {"full_name": "Jane Doe", "email": "jane@example.com"}
    return ParsedResumeData(**{**defaults, **overrides})


async def _parse(profile_repo, parsed: ParsedResumeData):
    """One parse pass against `profile_repo`, with a fresh resume and generator.

    A fresh `SequentialIdGenerator` per call means a second pass mints the same ids
    as the first. That is harmless *because* the dedup runs on content before any
    entry is added — if it regressed, the duplicate-id guard on `add_work_history`
    would raise, which is a second way these tests would notice.
    """
    resume_repo = InMemoryResumeRepo()
    uploaded = await _seed_resume(resume_repo)
    return await ParseResume(
        resume_repository=resume_repo,
        profile_repository=profile_repo,
        resume_parser=FakeResumeParser(parsed),
        id_generator=SequentialIdGenerator(),
    ).execute(uploaded.id, "user-1")


@pytest.mark.asyncio
async def test_re_parsing_the_same_resume_does_not_duplicate_work_history():
    """The defect this closes: uploading the same résumé twice doubled the
    candidate's employment history, and nothing could remove the copy."""
    profile_repo = InMemoryProfileRepo()
    parsed = _parsed(work_history=[_one_job()])

    await _parse(profile_repo, parsed)
    await _parse(profile_repo, parsed)

    stored = await profile_repo.get_by_user_id("user-1")
    assert stored is not None
    assert len(stored.work_history) == 1


@pytest.mark.asyncio
async def test_a_resume_listing_the_same_job_twice_stores_it_once():
    """Deduped within one batch as well as against the profile — the same two
    reasons the skills merge has always done it."""
    profile_repo = InMemoryProfileRepo()
    await _parse(profile_repo, _parsed(work_history=[_one_job(), _one_job()]))

    stored = await profile_repo.get_by_user_id("user-1")
    assert stored is not None
    assert len(stored.work_history) == 1


@pytest.mark.asyncio
async def test_casing_and_spacing_do_not_defeat_the_work_history_dedup():
    """Normalized with the same helper the job-dedup logic uses, so "ACME  Corp"
    and "Acme Corp" are one employer."""
    profile_repo = InMemoryProfileRepo()
    await _parse(
        profile_repo,
        _parsed(work_history=[_one_job(company="ACME  Corp", title="Engineer")]),
    )
    await _parse(
        profile_repo,
        _parsed(work_history=[_one_job(company="Acme Corp", title="engineer")]),
    )

    stored = await profile_repo.get_by_user_id("user-1")
    assert stored is not None
    assert len(stored.work_history) == 1


@pytest.mark.asyncio
async def test_two_stints_at_the_same_employer_are_kept_apart():
    """The start date is in the dedup key deliberately: contract-then-permanent in
    the same role is two real entries, and over-merging silently deletes history
    the candidate may have typed."""
    profile_repo = InMemoryProfileRepo()
    await _parse(
        profile_repo,
        _parsed(
            work_history=[
                _one_job(start=date(2018, 1, 1)),
                _one_job(start=date(2021, 6, 1)),
            ]
        ),
    )

    stored = await profile_repo.get_by_user_id("user-1")
    assert stored is not None
    assert len(stored.work_history) == 2


@pytest.mark.asyncio
async def test_a_promotion_is_not_merged_into_the_role_it_followed():
    """ "Engineer" and "Senior Engineer" stay separate even at one company on one
    start date — which is why the key is an exact normalized title rather than the
    substring-tolerant `titles_match`."""
    profile_repo = InMemoryProfileRepo()
    await _parse(
        profile_repo,
        _parsed(
            work_history=[
                _one_job(title="Engineer"),
                _one_job(title="Senior Engineer"),
            ]
        ),
    )

    stored = await profile_repo.get_by_user_id("user-1")
    assert stored is not None
    assert len(stored.work_history) == 2


@pytest.mark.asyncio
async def test_re_parsing_does_not_duplicate_education():
    profile_repo = InMemoryProfileRepo()
    parsed = _parsed(
        education=[
            ParsedEducationEntry(
                institution_name="State University",
                degree="BSc",
                start_date=date(2014, 9, 1),
            )
        ]
    )

    await _parse(profile_repo, parsed)
    await _parse(profile_repo, parsed)

    stored = await profile_repo.get_by_user_id("user-1")
    assert stored is not None
    assert len(stored.education) == 1


@pytest.mark.asyncio
async def test_a_hand_typed_job_survives_a_later_resume_upload_unduplicated():
    """The combination flow this dedup exists for, and the provenance check that
    makes it worth doing per entry: the job the candidate typed keeps saying they
    typed it, rather than being replaced by a parsed copy."""
    profile_repo = InMemoryProfileRepo()
    typed = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Jane Doe",
        email=EmailAddress("jane@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    typed.add_work_history(
        WorkHistoryEntry(
            id="typed-1",
            company_name="Acme",
            job_title="Engineer",
            start_date=date(2020, 1, 1),
            source=ProvenanceSource.USER_ENTERED,
        )
    )
    await profile_repo.add(typed)

    await _parse(
        profile_repo,
        _parsed(
            work_history=[
                _one_job(),
                _one_job(
                    company="Globex", title="Platform Engineer", start=date(2022, 3, 1)
                ),
            ]
        ),
    )

    stored = await profile_repo.get_by_user_id("user-1")
    assert stored is not None
    assert len(stored.work_history) == 2, "the new job lands, the known one does not"
    known = next(e for e in stored.work_history if e.company_name == "Acme")
    assert known.source is ProvenanceSource.USER_ENTERED


# ---- Filling gaps on a profile that already exists ---------------------------
#
# Parsing used to touch only work history, education and skills on an existing
# profile: contact details were set when the profile was *created* and never
# again, and links and address were never parsed at all. So a candidate who
# created a profile by hand and then uploaded a résumé got no contact data from
# it. These cover the two halves of the rule that replaced that — gaps are
# filled, and nothing already answered is overwritten.


async def _existing_profile(profile_repo, **overrides) -> UserProfile:
    defaults = {
        "id": "profile-existing",
        "user_id": "user-1",
        "full_name": "Jane Doe",
        "email": EmailAddress("jane@example.com"),
        "contact_source": ProvenanceSource.USER_ENTERED,
    }
    profile = UserProfile(**{**defaults, **overrides})
    await profile_repo.add(profile)
    return profile


@pytest.mark.asyncio
async def test_a_blank_contact_field_is_filled_from_the_resume():
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(
        profile_repo,
        _parsed(
            phone="555-1234",
            headline="Staff Engineer",
            location="Austin, TX",
            middle_name="Quinn",
            preferred_name="JD",
        ),
    )

    profile = profile_repo.store["profile-existing"]
    assert profile.phone == "555-1234"
    assert profile.headline == "Staff Engineer"
    assert profile.location == "Austin, TX"
    assert profile.middle_name == "Quinn"
    assert profile.preferred_name == "JD"


@pytest.mark.asyncio
async def test_a_contact_field_the_candidate_already_answered_is_not_overwritten():
    """The candidate may have corrected what the résumé says. Re-uploading it
    must not quietly put the old value back."""
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo, phone="+1 512 555 0100", location="Remote")

    await _parse(profile_repo, _parsed(phone="555-1234", location="Austin, TX"))

    profile = profile_repo.store["profile-existing"]
    assert profile.phone == "+1 512 555 0100"
    assert profile.location == "Remote"


@pytest.mark.asyncio
async def test_the_name_and_email_on_an_existing_profile_are_never_replaced():
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(
        profile_repo, _parsed(full_name="J. Doe", email="different@example.com")
    )

    profile = profile_repo.store["profile-existing"]
    assert profile.full_name == "Jane Doe"
    assert profile.email.value == "jane@example.com"


@pytest.mark.asyncio
async def test_filling_a_gap_does_not_downgrade_the_contact_provenance():
    """The group carries one source. Keeping the stronger existing tag cannot
    mislabel a fact the candidate did state — see `_fill_contact_gaps`."""
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(profile_repo, _parsed(phone="555-1234"))

    assert (
        profile_repo.store["profile-existing"].contact_source
        is ProvenanceSource.USER_ENTERED
    )


# ---- Address and links -------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_address_is_filled_from_the_resume():
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(
        profile_repo,
        _parsed(city="Austin", state_or_region="TX", country="United States"),
    )

    address = profile_repo.store["profile-existing"].address
    assert address.city == "Austin"
    assert address.state_or_region == "TX"
    assert address.country == "United States"
    # Not stated on the résumé, so left alone rather than guessed.
    assert address.street_address is None
    assert address.postal_code is None


@pytest.mark.asyncio
async def test_an_address_already_on_the_profile_is_left_untouched():
    """All-or-nothing: merging a parsed address into a typed one would leave the
    group's single source describing neither."""
    profile_repo = InMemoryProfileRepo()
    profile = await _existing_profile(profile_repo)
    profile.set_address(Address(city="Lisbon"), ProvenanceSource.USER_ENTERED)

    await _parse(profile_repo, _parsed(city="Austin", country="United States"))

    address = profile_repo.store["profile-existing"].address
    assert address.city == "Lisbon"
    assert address.country is None


@pytest.mark.asyncio
async def test_links_are_filled_from_the_resume_and_tagged_as_parsed():
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(
        profile_repo,
        _parsed(
            linkedin_url="https://www.linkedin.com/in/janedoe",
            github_url="https://github.com/janedoe",
        ),
    )

    profile = profile_repo.store["profile-existing"]
    assert profile.links.linkedin_url == "https://www.linkedin.com/in/janedoe"
    assert profile.links.github_url == "https://github.com/janedoe"
    assert profile.links_source is ProvenanceSource.PARSED_RESUME


@pytest.mark.asyncio
async def test_a_url_the_domain_refuses_is_dropped_without_failing_the_parse():
    """One unusable link in a résumé header must not cost the candidate their
    work history."""
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(
        profile_repo,
        _parsed(
            linkedin_url="not a url at all",
            github_url="https://github.com/janedoe",
            work_history=[_one_job()],
        ),
    )

    profile = profile_repo.store["profile-existing"]
    assert profile.links.linkedin_url is None
    assert profile.links.github_url == "https://github.com/janedoe"
    assert len(profile.work_history) == 1


@pytest.mark.asyncio
async def test_links_already_on_the_profile_are_left_untouched():
    profile_repo = InMemoryProfileRepo()
    profile = await _existing_profile(profile_repo)
    profile.set_links(
        ProfileLinks(linkedin_url="https://www.linkedin.com/in/typed"),
        ProvenanceSource.USER_ENTERED,
    )

    await _parse(profile_repo, _parsed(github_url="https://github.com/janedoe"))

    profile = profile_repo.store["profile-existing"]
    assert profile.links.linkedin_url == "https://www.linkedin.com/in/typed"
    assert profile.links.github_url is None


# ---- Majors and minors -------------------------------------------------------


@pytest.mark.asyncio
async def test_parsed_majors_and_minors_land_on_the_education_entry():
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(
        profile_repo,
        _parsed(
            education=[
                ParsedEducationEntry(
                    institution_name="UT Austin",
                    degree="B.S.",
                    majors=["Computer Science", "Mathematics"],
                    minors=["Economics"],
                )
            ]
        ),
    )

    entry = profile_repo.store["profile-existing"].education[0]
    assert entry.majors == ("Computer Science", "Mathematics")
    assert entry.minors == ("Economics",)


@pytest.mark.asyncio
async def test_a_single_field_of_study_is_read_as_one_major():
    """The fallback for a model answering in the older shape. Dropping it would
    lose the subject entirely."""
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(
        profile_repo,
        _parsed(
            education=[
                ParsedEducationEntry(
                    institution_name="UT Austin",
                    degree="B.S.",
                    field_of_study="Computer Science",
                )
            ]
        ),
    )

    entry = profile_repo.store["profile-existing"].education[0]
    assert entry.majors == ("Computer Science",)
    assert entry.minors == ()


@pytest.mark.asyncio
async def test_majors_win_over_the_legacy_field_when_both_are_present():
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(
        profile_repo,
        _parsed(
            education=[
                ParsedEducationEntry(
                    institution_name="UT Austin",
                    degree="B.S.",
                    majors=["Applied Mathematics"],
                    field_of_study="Something Else",
                )
            ]
        ),
    )

    assert profile_repo.store["profile-existing"].education[0].majors == (
        "Applied Mathematics",
    )


# ---- What parsing must never write ------------------------------------------


@pytest.mark.asyncio
async def test_parsing_never_writes_work_authorization_or_eeo():
    """The legal sections stay the candidate's own statement. `PARSED_RESUME` is
    excluded from `WorkAuthorization.ATTESTING_SOURCES`, so a parsed answer would
    be unusable for autofill anyway — but it must not be stored at all."""
    profile_repo = InMemoryProfileRepo()
    await _existing_profile(profile_repo)

    await _parse(profile_repo, _parsed(phone="555-1234", city="Austin"))

    profile = profile_repo.store["profile-existing"]
    assert profile.work_authorization is None
    assert profile.eeo_self_identification is None
