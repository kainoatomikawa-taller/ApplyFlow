"""Tests for ReviseGeneratedDocument — the candidate's edit of a generated
draft, held to the same provenance contract as the draft itself.

The interesting cases are all about that symmetry: an edit is stored as a
new version rather than replacing one, and the guard does not soften just
because a human typed the line. Shared fakes live in `conftest.py`.
"""

from __future__ import annotations

import pytest

from src.application.dtos.generation_dtos import ReviseGeneratedDocumentInput
from src.application.exceptions import UnattestedGenerationError
from src.application.services.application_document_archive import (
    ApplicationDocumentArchive,
)
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.application.use_cases.revise_generated_document import ReviseGeneratedDocument
from src.domain.exceptions import (
    InvalidValueError,
    JobPostingNotFoundError,
    ProfileNotFoundError,
)
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from tests.application.conftest import (
    InMemoryApplicationDocumentRepository,
    SequentialIdGenerator,
    StubAnswerMemoryRepository,
    StubJobPostingRepository,
    StubProfileRepository,
)

#: Two lines the candidate's record backs outright: the Acme role and what
#: they built there (see the `profile` fixture).
_BACKED_EDIT = "Backend Engineer, Acme Corp\nBuilt payment services in Python."


def _use_case(posting, fact_assembler, archive=None) -> ReviseGeneratedDocument:
    return ReviseGeneratedDocument(
        job_posting_repository=StubJobPostingRepository(posting),
        fact_assembler=fact_assembler,
        archive=archive
        or ApplicationDocumentArchive(
            repository=InMemoryApplicationDocumentRepository(),
            id_generator=SequentialIdGenerator(),
        ),
    )


def _revision(content: str, kind: str = "tailored_resume"):
    return ReviseGeneratedDocumentInput(
        user_id="user-1",
        job_posting_id="job-posting-1",
        document_kind=kind,
        content=content,
    )


@pytest.mark.asyncio
async def test_an_edit_the_record_backs_is_stored_verbatim(posting, fact_assembler):
    result = await _use_case(posting, fact_assembler).execute(_revision(_BACKED_EDIT))

    assert result.content == _BACKED_EDIT
    assert result.violations == []
    assert result.document_kind == "tailored_resume"


@pytest.mark.asyncio
async def test_the_stored_snapshot_is_the_edited_text(
    posting, fact_assembler, archive, document_repository
):
    """The point of the whole route: what the candidate approved is what the
    tracker reads back, not the draft they changed."""
    result = await _use_case(posting, fact_assembler, archive).execute(
        _revision(_BACKED_EDIT)
    )

    stored = await document_repository.get_by_id(result.document_id)
    assert stored is not None
    assert stored.content == _BACKED_EDIT
    assert stored.document_kind is GeneratedDocumentKind.TAILORED_RESUME


@pytest.mark.asyncio
async def test_an_edit_is_a_new_version_and_leaves_the_earlier_one_readable(
    posting, fact_assembler, archive, document_repository
):
    first = await _use_case(posting, fact_assembler, archive).execute(
        _revision(_BACKED_EDIT)
    )
    second = await _use_case(posting, fact_assembler, archive).execute(
        _revision("Built payment services in Python.")
    )

    assert (first.version, second.version) == (1, 2)
    assert first.document_id != second.document_id
    # The earlier version is still there, with its original text.
    original = await document_repository.get_by_id(first.document_id)
    assert original is not None
    assert original.content == _BACKED_EDIT


@pytest.mark.asyncio
async def test_a_claim_the_candidate_typed_themselves_is_still_stripped(
    posting, fact_assembler, document_repository, archive
):
    """The guard does not know which side of the boundary a line came from.
    An edit that adds Terraform — a requirement of the posting, and nothing
    the candidate's record backs — loses that line exactly as a model's
    invention would."""
    result = await _use_case(posting, fact_assembler, archive).execute(
        _revision(f"{_BACKED_EDIT}\nExpert in Terraform across three clouds.")
    )

    assert "Terraform" not in result.content
    assert result.content == _BACKED_EDIT
    assert "terraform" in result.violations[0].unsupported_terms
    # And the stored version is the stripped one, never the submitted one.
    stored = await document_repository.get_by_id(result.document_id)
    assert stored is not None
    assert "Terraform" not in stored.content


@pytest.mark.asyncio
async def test_an_edit_that_leaves_nothing_attested_is_refused(
    posting, fact_assembler, archive, document_repository
):
    """Headings and enthusiasm survive the guard while asserting nothing.
    Storing that as the document that went out would be a false record."""
    with pytest.raises(UnattestedGenerationError):
        await _use_case(posting, fact_assembler, archive).execute(
            _revision("Professional Summary\n\nI am excited about this opportunity.")
        )

    assert document_repository.documents == []


@pytest.mark.asyncio
async def test_naming_the_posting_is_not_treated_as_a_candidate_claim(
    posting, fact_assembler
):
    content = f"Applying to Globex in Austin, TX.\n{_BACKED_EDIT}"

    result = await _use_case(posting, fact_assembler).execute(_revision(content))

    assert result.content == content
    assert result.backing_sources == ["parsed_resume"]


@pytest.mark.asyncio
async def test_a_cover_letter_edit_uses_the_same_path(posting, fact_assembler, archive):
    result = await _use_case(posting, fact_assembler, archive).execute(
        _revision("Built payment services in Python.", kind="cover_letter")
    )

    assert result.document_kind == GeneratedDocumentKind.COVER_LETTER.value
    assert result.version == 1


@pytest.mark.asyncio
async def test_a_resume_edit_does_not_leave_a_heading_over_nothing(
    posting, fact_assembler
):
    """The candidate's edit puts an unbackable line under a heading; the
    guard takes the line and the formatter takes the heading with it."""
    result = await _use_case(posting, fact_assembler).execute(
        _revision(f"{_BACKED_EDIT}\n\nCertifications\nCertified Terraform Architect.\n")
    )

    assert "Certifications" not in result.content
    assert "Terraform" not in result.content


@pytest.mark.asyncio
async def test_an_unknown_document_kind_is_rejected_before_anything_is_read(
    posting, fact_assembler
):
    with pytest.raises(InvalidValueError):
        await _use_case(posting, fact_assembler).execute(
            _revision(_BACKED_EDIT, kind="interview_notes")
        )


@pytest.mark.asyncio
async def test_a_missing_posting_is_reported(fact_assembler):
    with pytest.raises(JobPostingNotFoundError):
        await _use_case(None, fact_assembler).execute(_revision(_BACKED_EDIT))


@pytest.mark.asyncio
async def test_a_candidate_with_no_profile_has_nothing_to_validate_against(posting):
    """No profile means no attested corpus, so there is no basis on which to
    store anything as the candidate's own words."""
    assembler = ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(None),
        answer_memory_repository=StubAnswerMemoryRepository(),
    )

    with pytest.raises(ProfileNotFoundError):
        await _use_case(posting, assembler).execute(_revision(_BACKED_EDIT))
