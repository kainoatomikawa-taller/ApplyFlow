"""Real-database smoke test for the sent-document snapshot store.

Exercises `SqlAlchemyApplicationDocumentRepository` against an actual
Postgres connection end to end: create a job posting, archive a resume and a
cover letter against it, add a second resume version, then read them back by
id, by latest-of-kind, per job, and per user. Also proves the two properties
the store's whole premise rests on — that a duplicate version is rejected by
the database, and that content edited out of band is refused on read rather
than served as authentic.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from src.application.exceptions import DocumentVersionConflictError
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import DocumentSnapshotIntegrityError
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.infrastructure.persistence.application_document_repository_impl import (
    SqlAlchemyApplicationDocumentRepository,
)
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.security.field_cipher import get_field_cipher
from src.infrastructure.security.sensitive_access import SensitiveDataAccess

_RESUME_V1 = "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)"
_RESUME_V2 = "EXPERIENCE\nBackend Engineer at Acme Corp\nSKILLS\nPython"
_LETTER = "Dear Hiring Manager,\n\nI led a team of 5 engineers.\n\nSincerely,"


@pytest.fixture(autouse=True)
def _sensitive_access(sensitive_access: SensitiveDataAccess) -> None:
    """Every test in this file round-trips at least one encrypted column, so the
    whole module runs inside a sensitive-data access scope — standing in for the
    authorized entry point a repository is always called from in production (Epic
    07). See `tests/conftest.py` for the shared fixture, and
    `test_encryption_at_rest.py` for the tests that assert the refusal when no
    scope is open."""


@pytest.fixture
async def schema_ready() -> AsyncIterator[None]:
    # The process-wide engine's pool outlives a test but its connections are
    # bound to the loop that opened them, so a pooled connection from the
    # previous test is unusable here. Disposing on both sides of each test
    # means every one of them opens its own — without it, only the first test
    # in this module would run and the rest would "skip" as unreachable.
    await engine.dispose()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")
    yield
    await engine.dispose()


async def _job_posting() -> JobPosting:
    posting = JobPosting(
        id=f"smoke-job-{uuid.uuid4()}",
        source="greenhouse",
        company="Smoke Test Co",
        title="Backend Engineer",
        apply_url="https://smoketestco.example.com/careers/documents",
        description="Build things.",
    )
    async with async_session_factory() as session:
        await SqlAlchemyJobPostingRepository(session).add(posting)
    return posting


def _snapshot(
    *,
    user_id: str,
    job_posting_id: str,
    kind: GeneratedDocumentKind,
    content: str,
    version: int,
) -> ApplicationDocument:
    return ApplicationDocument(
        id=f"smoke-doc-{uuid.uuid4()}",
        user_id=user_id,
        job_posting_id=job_posting_id,
        document_kind=kind,
        content=content,
        version=version,
        backing_sources=(ProvenanceSource.PARSED_RESUME, ProvenanceSource.ANSWER),
    )


@pytest.mark.asyncio
async def test_snapshots_round_trip_against_a_real_database(schema_ready: None) -> None:
    posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"
    resume_v1 = _snapshot(
        user_id=user_id,
        job_posting_id=posting.id,
        kind=GeneratedDocumentKind.TAILORED_RESUME,
        content=_RESUME_V1,
        version=1,
    )
    resume_v2 = _snapshot(
        user_id=user_id,
        job_posting_id=posting.id,
        kind=GeneratedDocumentKind.TAILORED_RESUME,
        content=_RESUME_V2,
        version=2,
    )
    letter = _snapshot(
        user_id=user_id,
        job_posting_id=posting.id,
        kind=GeneratedDocumentKind.COVER_LETTER,
        content=_LETTER,
        version=1,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationDocumentRepository(session)
        for document in (resume_v1, resume_v2, letter):
            await repository.add(document)

        # Read one back byte for byte, provenance and all.
        stored = await repository.get_by_id(resume_v1.id)
        assert stored is not None
        assert stored.content == _RESUME_V1
        assert stored.document_kind is GeneratedDocumentKind.TAILORED_RESUME
        assert stored.backing_sources == (
            ProvenanceSource.PARSED_RESUME,
            ProvenanceSource.ANSWER,
        )
        assert stored.version == 1

        # Version counting is per kind, which is what the archive numbers from.
        assert (
            await repository.count_versions(
                user_id=user_id,
                job_posting_id=posting.id,
                document_kind=GeneratedDocumentKind.TAILORED_RESUME,
            )
            == 2
        )
        assert (
            await repository.count_versions(
                user_id=user_id,
                job_posting_id=posting.id,
                document_kind=GeneratedDocumentKind.COVER_LETTER,
            )
            == 1
        )

        # "Latest" is the newest version, and each kind is tracked separately.
        latest_resume = await repository.get_latest(
            user_id=user_id,
            job_posting_id=posting.id,
            document_kind=GeneratedDocumentKind.TAILORED_RESUME,
        )
        assert latest_resume is not None
        assert latest_resume.id == resume_v2.id
        assert latest_resume.content == _RESUME_V2

        latest_letter = await repository.get_latest(
            user_id=user_id,
            job_posting_id=posting.id,
            document_kind=GeneratedDocumentKind.COVER_LETTER,
        )
        assert latest_letter is not None
        assert latest_letter.content == _LETTER

        # The superseded version is still there — an application already sent
        # cannot be un-sent.
        for_job = await repository.list_for_job(
            user_id=user_id, job_posting_id=posting.id
        )
        assert {d.id for d in for_job} == {resume_v1.id, resume_v2.id, letter.id}

        # The tracker's feed.
        for_user = await repository.list_by_user_id(user_id)
        assert {d.id for d in for_user} == {resume_v1.id, resume_v2.id, letter.id}

        # Another candidate sees none of it.
        assert await repository.list_by_user_id(f"other-{uuid.uuid4()}") == []


@pytest.mark.asyncio
async def test_a_duplicate_version_is_refused_by_the_database(
    schema_ready: None,
) -> None:
    """Two snapshots claiming the same version of the same document would
    leave the tracker guessing which one was sent."""
    posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"

    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationDocumentRepository(session)
        await repository.add(
            _snapshot(
                user_id=user_id,
                job_posting_id=posting.id,
                kind=GeneratedDocumentKind.COVER_LETTER,
                content=_LETTER,
                version=1,
            )
        )

        with pytest.raises(DocumentVersionConflictError):
            await repository.add(
                _snapshot(
                    user_id=user_id,
                    job_posting_id=posting.id,
                    kind=GeneratedDocumentKind.COVER_LETTER,
                    content="A different letter entirely.",
                    version=1,
                )
            )


@pytest.mark.asyncio
async def test_content_edited_out_of_band_is_refused_on_read(
    schema_ready: None,
) -> None:
    """Stands in for a manual UPDATE or a bad migration: the row's digest no
    longer describes its content, so it is not served as the sent document.

    The out-of-band edit is written as valid ciphertext, not as plaintext. That
    is deliberately the harder case now that `content` is encrypted (Epic 07):
    plaintext in that column is caught by the cipher before the digest is ever
    consulted, which would make this test pass for the wrong reason and stop
    saying anything about the integrity check. Substituting something that
    decrypts cleanly and simply is not what was stored is what the digest exists
    to catch — and it is what a bad migration re-encrypting the wrong value
    would actually produce.
    """
    posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"
    document = _snapshot(
        user_id=user_id,
        job_posting_id=posting.id,
        kind=GeneratedDocumentKind.TAILORED_RESUME,
        content=_RESUME_V1,
        version=1,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationDocumentRepository(session)
        await repository.add(document)

        await session.execute(
            text("UPDATE application_documents SET content = :content WHERE id = :id"),
            {
                "content": get_field_cipher().encrypt(
                    "PhD in Distributed Systems, Initech Institute",
                    purpose="application_documents.content",
                ),
                "id": document.id,
            },
        )
        await session.commit()

        with pytest.raises(DocumentSnapshotIntegrityError):
            await repository.get_by_id(document.id)
