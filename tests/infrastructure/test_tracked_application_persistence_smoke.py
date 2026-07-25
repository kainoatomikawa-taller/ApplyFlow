"""Real-database smoke test for the tracker's application record.

Exercises `SqlAlchemyTrackedApplicationRepository` against an actual Postgres
connection end to end: create a job posting, archive the resume and cover
letter that go out with the application, record the application against them,
then read it back by id, per user, and per job — and drive a status transition
through the store.

Also proves the two properties the tracker's premise rests on: that the stored
row still resolves to the *exact* Epic 04 snapshots that were sent (not
regenerated text), and that a row referencing a document or posting which does
not exist is refused at write time rather than becoming a tracker entry unable
to show what was sent.

Skips (rather than fails) when no database is reachable, so `pytest` still runs
for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.application.exceptions import TrackedApplicationReferenceError
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.value_objects.application_status import ApplicationStatus
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
from src.infrastructure.persistence.tracked_application_repository_impl import (
    SqlAlchemyTrackedApplicationRepository,
)

_RESUME = "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)"
_LETTER = "Dear Hiring Manager,\n\nI led a team of 5 engineers.\n\nSincerely,"


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


async def _job_posting(title: str = "Backend Engineer") -> JobPosting:
    posting = JobPosting(
        id=f"smoke-job-{uuid.uuid4()}",
        source="greenhouse",
        company="Smoke Test Co",
        title=title,
        apply_url="https://smoketestco.example.com/careers/tracker",
        description="Build things.",
    )
    async with async_session_factory() as session:
        await SqlAlchemyJobPostingRepository(session).add(posting)
    return posting


async def _archived_documents(
    *, user_id: str, job_posting_id: str, with_letter: bool = True
) -> tuple[ApplicationDocument, ApplicationDocument | None]:
    """Store the Epic 04 snapshots this application is sent with."""
    resume = ApplicationDocument(
        id=f"smoke-doc-{uuid.uuid4()}",
        user_id=user_id,
        job_posting_id=job_posting_id,
        document_kind=GeneratedDocumentKind.TAILORED_RESUME,
        content=_RESUME,
        version=1,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )
    letter = (
        ApplicationDocument(
            id=f"smoke-doc-{uuid.uuid4()}",
            user_id=user_id,
            job_posting_id=job_posting_id,
            document_kind=GeneratedDocumentKind.COVER_LETTER,
            content=_LETTER,
            version=1,
            backing_sources=(ProvenanceSource.ANSWER,),
        )
        if with_letter
        else None
    )
    async with async_session_factory() as session:
        repository = SqlAlchemyApplicationDocumentRepository(session)
        await repository.add(resume)
        if letter is not None:
            await repository.add(letter)
    return resume, letter


@pytest.mark.asyncio
async def test_a_tracked_application_round_trips_against_a_real_database(
    schema_ready: None,
) -> None:
    """The ticket's acceptance criterion 4: create and read an application
    record through the data-access layer."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting(title="Senior Backend Engineer")
    resume, letter = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id
    )
    assert letter is not None
    applied_at = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)

    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        resume_document=resume,
        cover_letter_document=letter,
        applied_at=applied_at,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(tracked)

        stored = await repository.get_by_id(tracked.id)

    assert stored is not None
    # Role, company, date, status, and the job reference — criterion 1.
    assert stored.role_title == "Senior Backend Engineer"
    assert stored.company_name == "Smoke Test Co"
    assert stored.applied_at == applied_at
    assert stored.status is ApplicationStatus.APPLIED
    assert stored.job_posting_id == posting.id
    # The exact stored documents — criterion 2.
    assert stored.resume_document_id == resume.id
    assert stored.cover_letter_document_id == letter.id


@pytest.mark.asyncio
async def test_the_stored_row_resolves_to_the_documents_that_were_sent(
    schema_ready: None,
) -> None:
    """The point of storing ids rather than text: the tracker reads back the
    archived snapshot itself, byte for byte, instead of anything regenerated."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, letter = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id
    )
    assert letter is not None

    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        resume_document=resume,
        cover_letter_document=letter,
    )

    async with async_session_factory() as session:
        await SqlAlchemyTrackedApplicationRepository(session).add(tracked)

    async with async_session_factory() as session:
        applications = SqlAlchemyTrackedApplicationRepository(session)
        documents = SqlAlchemyApplicationDocumentRepository(session)

        stored = await applications.get_by_id(tracked.id)
        assert stored is not None

        sent_resume = await documents.get_by_id(stored.resume_document_id)
        assert stored.cover_letter_document_id is not None
        sent_letter = await documents.get_by_id(stored.cover_letter_document_id)

    assert sent_resume is not None
    assert sent_resume.content == _RESUME
    assert sent_resume.document_kind is GeneratedDocumentKind.TAILORED_RESUME
    assert sent_letter is not None
    assert sent_letter.content == _LETTER
    assert sent_letter.document_kind is GeneratedDocumentKind.COVER_LETTER


@pytest.mark.asyncio
async def test_a_status_transition_is_persisted(schema_ready: None) -> None:
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )

    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        resume_document=resume,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(tracked)

        tracked.change_status(ApplicationStatus.INTERVIEWING)
        await repository.update(tracked)

    async with async_session_factory() as session:
        stored = await SqlAlchemyTrackedApplicationRepository(session).get_by_id(
            tracked.id
        )

    assert stored is not None
    assert stored.status is ApplicationStatus.INTERVIEWING
    # No cover letter was sent with this one, and that stayed an honest absence.
    assert stored.cover_letter_document_id is None


@pytest.mark.asyncio
async def test_the_tracker_feed_lists_a_candidates_applications_newest_first(
    schema_ready: None,
) -> None:
    user_id = f"smoke-user-{uuid.uuid4()}"
    older_posting = await _job_posting(title="Platform Engineer")
    newer_posting = await _job_posting(title="Staff Engineer")

    older_resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=older_posting.id, with_letter=False
    )
    newer_resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=newer_posting.id, with_letter=False
    )

    now = datetime.now(UTC)
    older = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=older_posting,
        resume_document=older_resume,
        applied_at=now - timedelta(days=30),
    )
    newer = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=newer_posting,
        resume_document=newer_resume,
        applied_at=now - timedelta(days=1),
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(older)
        await repository.add(newer)

        feed = await repository.list_by_user_id(user_id)

        # Another candidate sees none of it.
        assert await repository.list_by_user_id(f"other-{uuid.uuid4()}") == []

    assert [application.id for application in feed] == [newer.id, older.id]
    assert [application.role_title for application in feed] == [
        "Staff Engineer",
        "Platform Engineer",
    ]


@pytest.mark.asyncio
async def test_applying_to_the_same_posting_twice_is_two_records(
    schema_ready: None,
) -> None:
    """Deliberately not constrained to one row per posting: a candidate who
    applies again months later has made two applications, each with its own
    date, documents, and outcome."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()

    first_resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )
    # A second, separately archived resume — a real re-application is tailored
    # again, so it carries its own snapshot.
    second_resume = ApplicationDocument(
        id=f"smoke-doc-{uuid.uuid4()}",
        user_id=user_id,
        job_posting_id=posting.id,
        document_kind=GeneratedDocumentKind.TAILORED_RESUME,
        content=f"{_RESUME}\nSKILLS\nPython, Postgres",
        version=2,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )
    async with async_session_factory() as session:
        await SqlAlchemyApplicationDocumentRepository(session).add(second_resume)

    now = datetime.now(UTC)
    first = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        resume_document=first_resume,
        applied_at=now - timedelta(days=180),
    )
    second = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        resume_document=second_resume,
        applied_at=now,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(first)
        await repository.add(second)

        for_job = await repository.list_for_job(
            user_id=user_id, job_posting_id=posting.id
        )

    assert [application.id for application in for_job] == [second.id, first.id]
    # Each kept the resume it actually went out with.
    assert for_job[0].resume_document_id == second_resume.id
    assert for_job[1].resume_document_id == first_resume.id


@pytest.mark.asyncio
async def test_an_unresolvable_document_reference_is_refused_at_write_time(
    schema_ready: None,
) -> None:
    """A tracker row whose documents point nowhere cannot show what was sent,
    so it never becomes a row."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()

    dangling = TrackedApplication(
        id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting_id=posting.id,
        company_name=posting.company,
        role_title=posting.title,
        applied_at=datetime.now(UTC),
        resume_document_id=f"never-stored-{uuid.uuid4()}",
    )

    async with async_session_factory() as session:
        with pytest.raises(TrackedApplicationReferenceError):
            await SqlAlchemyTrackedApplicationRepository(session).add(dangling)


@pytest.mark.asyncio
async def test_an_unresolvable_job_reference_is_refused_at_write_time(
    schema_ready: None,
) -> None:
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )

    orphaned = TrackedApplication(
        id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting_id=f"never-ingested-{uuid.uuid4()}",
        company_name="Smoke Test Co",
        role_title="Backend Engineer",
        applied_at=datetime.now(UTC),
        resume_document_id=resume.id,
    )

    async with async_session_factory() as session:
        with pytest.raises(TrackedApplicationReferenceError):
            await SqlAlchemyTrackedApplicationRepository(session).add(orphaned)


@pytest.mark.asyncio
async def test_a_posting_applied_to_cannot_be_deleted_out_from_under_the_record(
    schema_ready: None,
) -> None:
    """ON DELETE RESTRICT: this row states that an application was sent, so it
    must not disappear as a side effect of pruning postings."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )
    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        resume_document=resume,
    )

    async with async_session_factory() as session:
        await SqlAlchemyTrackedApplicationRepository(session).add(tracked)

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text("DELETE FROM job_postings WHERE id = :id"), {"id": posting.id}
            )
            await session.commit()
