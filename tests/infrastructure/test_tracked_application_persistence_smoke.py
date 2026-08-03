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

from src.application.exceptions import (
    ApplicationAlreadyLoggedError,
    TrackedApplicationReferenceError,
)
from src.application.services.submitted_application_log import SubmittedApplicationLog
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.canonical_job_identity import CanonicalJobIdentity
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
from src.infrastructure.security.sensitive_access import SensitiveDataAccess

_RESUME = "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)"
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
        submission_key=f"smoke-review-{uuid.uuid4()}",
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
        submission_key=f"smoke-review-{uuid.uuid4()}",
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
        submission_key=f"smoke-review-{uuid.uuid4()}",
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
        submission_key=f"smoke-review-{uuid.uuid4()}",
        resume_document=older_resume,
        applied_at=now - timedelta(days=30),
    )
    newer = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=newer_posting,
        submission_key=f"smoke-review-{uuid.uuid4()}",
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
        submission_key=f"smoke-review-{uuid.uuid4()}",
        resume_document=first_resume,
        applied_at=now - timedelta(days=180),
    )
    second = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        submission_key=f"smoke-review-{uuid.uuid4()}",
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
        submission_key=f"smoke-review-{uuid.uuid4()}",
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
        submission_key=f"smoke-review-{uuid.uuid4()}",
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
        submission_key=f"smoke-review-{uuid.uuid4()}",
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


@pytest.mark.asyncio
async def test_the_same_submission_key_is_refused_by_the_database(
    schema_ready: None,
) -> None:
    """The idempotency guarantee, at the level that actually enforces it. Two
    concurrent logs of one submission can both pass a "already logged?" read,
    so the constraint is what makes exactly-once real."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )
    submission_key = f"smoke-review-{uuid.uuid4()}"

    def _tracked() -> TrackedApplication:
        return TrackedApplication.record_sent(
            application_id=f"smoke-tracked-{uuid.uuid4()}",
            user_id=user_id,
            job_posting=posting,
            submission_key=submission_key,
            resume_document=resume,
        )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(_tracked())

        # A different row id, but the same submission — refused, and reported
        # as "already logged" rather than as a dangling reference.
        with pytest.raises(ApplicationAlreadyLoggedError):
            await repository.add(_tracked())


@pytest.mark.asyncio
async def test_the_same_key_for_a_different_candidate_is_allowed(
    schema_ready: None,
) -> None:
    """The constraint is scoped per candidate: two people's submissions must
    never collide with each other."""
    posting = await _job_posting()
    submission_key = "shared-key"

    for _ in range(2):
        user_id = f"smoke-user-{uuid.uuid4()}"
        resume, _ = await _archived_documents(
            user_id=user_id, job_posting_id=posting.id, with_letter=False
        )
        async with async_session_factory() as session:
            await SqlAlchemyTrackedApplicationRepository(session).add(
                TrackedApplication.record_sent(
                    application_id=f"smoke-tracked-{uuid.uuid4()}",
                    user_id=user_id,
                    job_posting=posting,
                    submission_key=submission_key,
                    resume_document=resume,
                )
            )


@pytest.mark.asyncio
async def test_the_log_service_is_idempotent_against_a_real_database(
    schema_ready: None,
) -> None:
    """End to end through `SubmittedApplicationLog`: the same submission logged
    twice leaves one record, linked to the exact stored snapshots."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting(title="Staff Backend Engineer")
    resume, letter = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id
    )
    assert letter is not None
    submission_key = f"smoke-review-{uuid.uuid4()}"
    applied_at = datetime(2026, 7, 22, 14, 5, tzinfo=UTC)

    class _Ids:
        def new_id(self) -> str:
            return f"smoke-tracked-{uuid.uuid4()}"

    async def _log_once() -> TrackedApplication:
        async with async_session_factory() as session:
            service = SubmittedApplicationLog(
                tracked_application_repository=(
                    SqlAlchemyTrackedApplicationRepository(session)
                ),
                document_repository=SqlAlchemyApplicationDocumentRepository(session),
                job_posting_repository=SqlAlchemyJobPostingRepository(session),
                id_generator=_Ids(),  # type: ignore[arg-type]
            )
            return await service.record(
                user_id=user_id,
                job_posting_id=posting.id,
                submission_key=submission_key,
                applied_at=applied_at,
            )

    first = await _log_once()
    second = await _log_once()

    assert second.id == first.id
    assert first.role_title == "Staff Backend Engineer"
    assert first.company_name == "Smoke Test Co"
    assert first.applied_at == applied_at
    # Reused the archived snapshots rather than anything regenerated.
    assert first.resume_document_id == resume.id
    assert first.cover_letter_document_id == letter.id

    async with async_session_factory() as session:
        rows = await SqlAlchemyTrackedApplicationRepository(session).list_by_user_id(
            user_id
        )
    assert len(rows) == 1


# ---- status history and status queries --------------------------------------
#
# The ticket's criteria 2, 3, and 4 against a real database: history is
# preserved across writes, it survives the round trip in order, and status is
# filterable in the query rather than in Python.


@pytest.mark.asyncio
async def test_the_full_status_history_survives_the_round_trip(
    schema_ready: None,
) -> None:
    """Criterion 2: the history is preserved, in order, with each entry naming
    where it came from — not collapsed into the current status."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )
    applied_at = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        submission_key=f"smoke-review-{uuid.uuid4()}",
        resume_document=resume,
        applied_at=applied_at,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(tracked)

    # Three separate transactions, as three real updates would be.
    for target, offset, note in (
        (ApplicationStatus.INTERVIEWING, 7, "recruiter screen"),
        (ApplicationStatus.OFFER, 21, "verbal offer"),
        (ApplicationStatus.REJECTED, 30, ""),
    ):
        async with async_session_factory() as session:
            repository = SqlAlchemyTrackedApplicationRepository(session)
            loaded = await repository.get_by_id(tracked.id)
            assert loaded is not None
            loaded.change_status(
                target, note=note, changed_at=applied_at + timedelta(days=offset)
            )
            await repository.update(loaded)

    async with async_session_factory() as session:
        stored = await SqlAlchemyTrackedApplicationRepository(session).get_by_id(
            tracked.id
        )

    assert stored is not None
    assert stored.status is ApplicationStatus.REJECTED
    assert [entry.status for entry in stored.status_history] == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
    ]
    assert [entry.previous_status for entry in stored.status_history] == [
        None,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFER,
    ]
    assert stored.status_history[1].note == "recruiter screen"
    assert stored.status_history[1].changed_at == applied_at + timedelta(days=7)
    # The rejection is terminal, and the history still shows the interview and
    # the offer that came before it.
    assert not stored.is_open
    assert stored.has_held_status(ApplicationStatus.OFFER)
    assert stored.current_status_since == applied_at + timedelta(days=30)


@pytest.mark.asyncio
async def test_recording_an_application_stores_its_first_history_entry(
    schema_ready: None,
) -> None:
    """A newly logged application already has a history — the entry for being
    sent — so nothing has to invent one on the first read."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )
    applied_at = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)

    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        submission_key=f"smoke-review-{uuid.uuid4()}",
        resume_document=resume,
        applied_at=applied_at,
    )

    async with async_session_factory() as session:
        await SqlAlchemyTrackedApplicationRepository(session).add(tracked)

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT sequence, status, previous_status, note "
                    "FROM application_status_events "
                    "WHERE tracked_application_id = :id ORDER BY sequence"
                ),
                {"id": tracked.id},
            )
        ).all()

    assert rows == [(0, "applied", None, "")]


@pytest.mark.asyncio
async def test_an_update_appends_rather_than_rewriting_history(
    schema_ready: None,
) -> None:
    """The history is append-only in the store, not just in the entity: an
    update inserts the new entry and leaves the stored ones untouched."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )

    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        submission_key=f"smoke-review-{uuid.uuid4()}",
        resume_document=resume,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(tracked)
        tracked.change_status(ApplicationStatus.INTERVIEWING)
        await repository.update(tracked)
        # Saving again with no further change must not duplicate anything —
        # the primary key on (application, sequence) is what guarantees it.
        await repository.update(tracked)

    async with async_session_factory() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM application_status_events "
                    "WHERE tracked_application_id = :id"
                ),
                {"id": tracked.id},
            )
        ).scalar()

    assert count == 2


@pytest.mark.asyncio
async def test_the_feed_can_be_filtered_by_status_in_the_query(
    schema_ready: None,
) -> None:
    """Criterion 4: status is queryable. Filtered in SQL, which is what keeps
    the tracker's views from getting slower as a search gets longer."""
    user_id = f"smoke-user-{uuid.uuid4()}"

    wanted: dict[ApplicationStatus, str] = {}
    for index, status in enumerate(
        (
            ApplicationStatus.APPLIED,
            ApplicationStatus.INTERVIEWING,
            ApplicationStatus.REJECTED,
        )
    ):
        # A posting each: `application_documents` allows one version-1 resume
        # per (candidate, posting, kind), so three applications need three
        # postings rather than three resumes for one.
        posting = await _job_posting()
        resume, _ = await _archived_documents(
            user_id=user_id, job_posting_id=posting.id, with_letter=False
        )
        tracked = TrackedApplication.record_sent(
            application_id=f"smoke-tracked-{uuid.uuid4()}",
            user_id=user_id,
            job_posting=posting,
            submission_key=f"smoke-review-{uuid.uuid4()}",
            resume_document=resume,
            applied_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC) + timedelta(days=index),
        )
        async with async_session_factory() as session:
            repository = SqlAlchemyTrackedApplicationRepository(session)
            await repository.add(tracked)
            if status is not ApplicationStatus.APPLIED:
                tracked.change_status(status)
                await repository.update(tracked)
        wanted[status] = tracked.id

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)

        everything = await repository.list_by_user_id(user_id)
        interviewing = await repository.list_by_user_id(
            user_id, statuses=[ApplicationStatus.INTERVIEWING]
        )
        live = await repository.list_by_user_id(
            user_id,
            statuses=[ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEWING],
        )
        none_of_them = await repository.list_by_user_id(user_id, statuses=[])

    assert len(everything) == 3
    assert [a.id for a in interviewing] == [wanted[ApplicationStatus.INTERVIEWING]]
    assert {a.id for a in live} == {
        wanted[ApplicationStatus.APPLIED],
        wanted[ApplicationStatus.INTERVIEWING],
    }
    # An empty filter means "no status is acceptable", not "no filter".
    assert none_of_them == []
    # Every application in the feed carries its own history.
    assert all(application.status_history for application in everything)


@pytest.mark.asyncio
async def test_history_is_removed_with_the_application_it_belongs_to(
    schema_ready: None,
) -> None:
    """The one CASCADE on the tracker. History without its application is
    unreadable, so it is a part-of rather than a reference-to."""
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = await _job_posting()
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )

    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        submission_key=f"smoke-review-{uuid.uuid4()}",
        resume_document=resume,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(tracked)
        tracked.change_status(ApplicationStatus.WITHDRAWN)
        await repository.update(tracked)

    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM tracked_applications WHERE id = :id"),
            {"id": tracked.id},
        )
        await session.commit()

    async with async_session_factory() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM application_status_events "
                    "WHERE tracked_application_id = :id"
                ),
                {"id": tracked.id},
            )
        ).scalar()

    assert count == 0


@pytest.mark.asyncio
async def test_applied_identities_come_back_normalized_and_deduplicated(
    schema_ready: None,
) -> None:
    """The read the matching layer suppresses on, against real SQL.

    Two things a fake cannot prove: that the snapshotted location actually
    round-trips through the new column, and that identities arrive collapsed
    by the *domain's* rule rather than by Postgres — "Smoke Test Co" and
    "SMOKE TEST  CO" are two rows to a `SELECT DISTINCT` and one role here.
    """
    user_id = f"smoke-user-{uuid.uuid4()}"
    other_user_id = f"smoke-user-{uuid.uuid4()}"

    async def _record(
        *,
        owner_id: str,
        company: str,
        title: str,
        location: str | None,
    ) -> None:
        posting = JobPosting(
            id=f"smoke-job-{uuid.uuid4()}",
            source="greenhouse",
            company=company,
            title=title,
            apply_url="https://smoketestco.example.com/careers/tracker",
            description="Build things.",
            location=location,
        )
        async with async_session_factory() as session:
            await SqlAlchemyJobPostingRepository(session).add(posting)
        resume, _ = await _archived_documents(
            user_id=owner_id, job_posting_id=posting.id, with_letter=False
        )
        tracked = TrackedApplication.record_sent(
            application_id=f"smoke-tracked-{uuid.uuid4()}",
            user_id=owner_id,
            job_posting=posting,
            submission_key=f"smoke-review-{uuid.uuid4()}",
            resume_document=resume,
        )
        async with async_session_factory() as session:
            await SqlAlchemyTrackedApplicationRepository(session).add(tracked)

    await _record(
        owner_id=user_id,
        company="Smoke Test Co",
        title="Backend Engineer",
        location="New York, NY",
    )
    # The same role written differently — one identity, two rows.
    await _record(
        owner_id=user_id,
        company="SMOKE TEST  CO",
        title="backend engineer",
        location="new york, ny",
    )
    # Same role, another city — a distinct identity.
    await _record(
        owner_id=user_id,
        company="Smoke Test Co",
        title="Backend Engineer",
        location="Berlin, DE",
    )
    # Another candidate's application must not leak into this answer.
    await _record(
        owner_id=other_user_id,
        company="Other Co",
        title="Backend Engineer",
        location="New York, NY",
    )

    async with async_session_factory() as session:
        identities = await SqlAlchemyTrackedApplicationRepository(
            session
        ).list_applied_identities(user_id=user_id)

    assert set(identities) == {
        CanonicalJobIdentity.of(
            company="Smoke Test Co", title="Backend Engineer", location="New York, NY"
        ),
        CanonicalJobIdentity.of(
            company="Smoke Test Co", title="Backend Engineer", location="Berlin, DE"
        ),
    }


@pytest.mark.asyncio
async def test_the_snapshotted_location_round_trips(schema_ready: None) -> None:
    user_id = f"smoke-user-{uuid.uuid4()}"
    posting = JobPosting(
        id=f"smoke-job-{uuid.uuid4()}",
        source="greenhouse",
        company="Smoke Test Co",
        title="Backend Engineer",
        apply_url="https://smoketestco.example.com/careers/tracker",
        description="Build things.",
        location="Berlin, DE",
    )
    async with async_session_factory() as session:
        await SqlAlchemyJobPostingRepository(session).add(posting)
    resume, _ = await _archived_documents(
        user_id=user_id, job_posting_id=posting.id, with_letter=False
    )
    tracked = TrackedApplication.record_sent(
        application_id=f"smoke-tracked-{uuid.uuid4()}",
        user_id=user_id,
        job_posting=posting,
        submission_key=f"smoke-review-{uuid.uuid4()}",
        resume_document=resume,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyTrackedApplicationRepository(session)
        await repository.add(tracked)
        stored = await repository.get_by_id(tracked.id)

    assert stored is not None
    assert stored.job_location == "Berlin, DE"
    assert stored.canonical_identity == posting.canonical_identity
