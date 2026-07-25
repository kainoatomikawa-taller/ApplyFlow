"""Tests for SubmittedApplicationLog — logging a sent application exactly once,
against the documents that actually went out.

Fakes rather than a database, per the layer's testing convention. The one thing
the fakes model faithfully is the unique constraint on
(`user_id`, `submission_key`), because the idempotency guarantee is that
constraint: a fake that let a duplicate through would prove the opposite of
what these tests claim.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.exceptions import (
    ApplicationAlreadyLoggedError,
    TrackedApplicationReferenceError,
)
from src.application.services.submitted_application_log import SubmittedApplicationLog
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.exceptions import (
    InvalidValueError,
    JobPostingNotFoundError,
    NoStoredApplicationDocumentError,
)
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource

_USER_ID = "user-1"
_JOB_ID = "job-1"
_SUBMISSION_KEY = "review-1"
_APPLIED_AT = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)


class FakeTrackedApplicationRepository:
    def __init__(self) -> None:
        self.rows: dict[str, TrackedApplication] = {}
        self.add_calls = 0

    async def add(self, application: TrackedApplication) -> None:
        self.add_calls += 1
        # The unique constraint the real schema enforces.
        for existing in self.rows.values():
            if (
                existing.user_id == application.user_id
                and existing.submission_key == application.submission_key
            ):
                raise ApplicationAlreadyLoggedError(
                    user_id=application.user_id,
                    submission_key=application.submission_key,
                )
        self.rows[application.id] = application

    async def get_by_id(self, application_id: str) -> TrackedApplication | None:
        return self.rows.get(application_id)

    async def get_by_submission_key(
        self, *, user_id: str, submission_key: str
    ) -> TrackedApplication | None:
        for existing in self.rows.values():
            if (
                existing.user_id == user_id
                and existing.submission_key == submission_key
            ):
                return existing
        return None

    async def update(self, application: TrackedApplication) -> None:
        self.rows[application.id] = application

    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[TrackedApplication]:
        return [r for r in self.rows.values() if r.user_id == user_id][:limit]

    async def list_for_job(
        self, *, user_id: str, job_posting_id: str
    ) -> list[TrackedApplication]:
        return [
            r
            for r in self.rows.values()
            if r.user_id == user_id and r.job_posting_id == job_posting_id
        ]


class FakeDocumentRepository:
    """Only the two reads the log performs; `get_latest` is the documented
    "what this application went out with"."""

    def __init__(self, documents: list[ApplicationDocument] | None = None) -> None:
        self.documents = documents or []

    async def get_latest(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
    ) -> ApplicationDocument | None:
        matches = [
            d
            for d in self.documents
            if d.user_id == user_id
            and d.job_posting_id == job_posting_id
            and d.document_kind is document_kind
        ]
        return max(matches, key=lambda d: d.version) if matches else None

    async def add(self, document: ApplicationDocument) -> None:
        self.documents.append(document)

    async def get_by_id(self, document_id: str) -> ApplicationDocument | None:
        return next((d for d in self.documents if d.id == document_id), None)

    async def count_versions(self, **kwargs: object) -> int:
        return len(self.documents)

    async def list_for_job(self, **kwargs: object) -> list[ApplicationDocument]:
        return list(self.documents)

    async def list_by_user_id(
        self, *args: object, **kwargs: object
    ) -> list[ApplicationDocument]:
        return list(self.documents)


class FakeJobPostingRepository:
    def __init__(self, postings: list[JobPosting] | None = None) -> None:
        self.postings = postings or []

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        return next((p for p in self.postings if p.id == job_posting_id), None)


class SequentialIdGenerator:
    def __init__(self) -> None:
        self.count = 0

    def new_id(self) -> str:
        self.count += 1
        return f"tracked-{self.count}"


def _posting() -> JobPosting:
    return JobPosting(
        id=_JOB_ID,
        source="greenhouse",
        company="Globex",
        title="Senior Backend Engineer",
        apply_url="https://boards.greenhouse.io/globex/jobs/1",
        description="Build the thing.",
    )


def _document(
    *,
    document_id: str,
    kind: GeneratedDocumentKind,
    version: int = 1,
    content: str = "EXPERIENCE\nBackend Engineer at Acme",
) -> ApplicationDocument:
    return ApplicationDocument(
        id=document_id,
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        document_kind=kind,
        content=content,
        version=version,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )


def _log(
    *,
    applications: FakeTrackedApplicationRepository | None = None,
    documents: list[ApplicationDocument] | None = None,
    postings: list[JobPosting] | None = None,
) -> tuple[SubmittedApplicationLog, FakeTrackedApplicationRepository]:
    repository = applications or FakeTrackedApplicationRepository()
    if documents is None:
        documents = [
            _document(
                document_id="doc-resume", kind=GeneratedDocumentKind.TAILORED_RESUME
            ),
            _document(
                document_id="doc-letter", kind=GeneratedDocumentKind.COVER_LETTER
            ),
        ]
    service = SubmittedApplicationLog(
        tracked_application_repository=repository,  # type: ignore[arg-type]
        document_repository=FakeDocumentRepository(documents),  # type: ignore[arg-type]
        job_posting_repository=FakeJobPostingRepository(  # type: ignore[arg-type]
            postings if postings is not None else [_posting()]
        ),
        id_generator=SequentialIdGenerator(),  # type: ignore[arg-type]
    )
    return service, repository


# ---- criterion 1: a record is logged on submission --------------------------


async def test_a_submission_is_logged_as_a_tracked_application() -> None:
    service, repository = _log()

    logged = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )

    assert logged.id in repository.rows
    assert logged.status is ApplicationStatus.APPLIED
    assert logged.submission_key == _SUBMISSION_KEY


# ---- criterion 2: the exact sent documents, reused ---------------------------


async def test_the_exact_stored_snapshots_are_linked() -> None:
    service, _ = _log()

    logged = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )

    assert logged.resume_document_id == "doc-resume"
    assert logged.cover_letter_document_id == "doc-letter"


async def test_the_newest_stored_version_is_the_one_linked() -> None:
    """`get_latest` is the documented "what this application went out with", so
    a revision made before submitting is what gets recorded."""
    service, _ = _log(
        documents=[
            _document(
                document_id="doc-resume-v1",
                kind=GeneratedDocumentKind.TAILORED_RESUME,
                version=1,
            ),
            _document(
                document_id="doc-resume-v2",
                kind=GeneratedDocumentKind.TAILORED_RESUME,
                version=2,
                content="EXPERIENCE\nBackend Engineer at Acme\nSKILLS\nPython",
            ),
        ]
    )

    logged = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )

    assert logged.resume_document_id == "doc-resume-v2"


async def test_a_missing_resume_snapshot_is_an_error_not_a_regeneration() -> None:
    """The service has no generator and must not invent what was sent. Logging
    an application with an empty resume reference is equally unacceptable."""
    service, repository = _log(
        documents=[
            _document(document_id="doc-letter", kind=GeneratedDocumentKind.COVER_LETTER)
        ]
    )

    with pytest.raises(NoStoredApplicationDocumentError):
        await service.record(
            user_id=_USER_ID,
            job_posting_id=_JOB_ID,
            submission_key=_SUBMISSION_KEY,
            applied_at=_APPLIED_AT,
        )

    assert repository.rows == {}


async def test_an_application_with_no_cover_letter_is_logged_without_one() -> None:
    service, _ = _log(
        documents=[
            _document(
                document_id="doc-resume", kind=GeneratedDocumentKind.TAILORED_RESUME
            )
        ]
    )

    logged = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )

    assert logged.cover_letter_document_id is None


# ---- criterion 3: role, company, date captured automatically ----------------


async def test_role_company_and_date_are_captured_without_being_passed_in() -> None:
    """The caller supplies the posting id and the submission time — never a
    role or company label that could disagree with the posting."""
    service, _ = _log()

    logged = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )

    assert logged.role_title == "Senior Backend Engineer"
    assert logged.company_name == "Globex"
    assert logged.applied_at == _APPLIED_AT
    assert logged.job_posting_id == _JOB_ID


async def test_an_unknown_posting_is_refused() -> None:
    service, repository = _log(postings=[])

    with pytest.raises(JobPostingNotFoundError):
        await service.record(
            user_id=_USER_ID,
            job_posting_id=_JOB_ID,
            submission_key=_SUBMISSION_KEY,
            applied_at=_APPLIED_AT,
        )

    assert repository.rows == {}


# ---- criterion 4: reliable and idempotent -----------------------------------


async def test_logging_the_same_submission_twice_returns_the_same_record() -> None:
    service, repository = _log()

    first = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )
    second = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )

    assert second.id == first.id
    assert len(repository.rows) == 1


async def test_a_retry_does_not_move_the_recorded_date() -> None:
    """A second log of the same submission must not rewrite when the
    application was sent."""
    service, _ = _log()

    first = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )
    second = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    assert second.applied_at == first.applied_at == _APPLIED_AT


async def test_a_status_change_survives_a_later_duplicate_log() -> None:
    """The idempotent path returns the stored row as it is now — a re-log must
    not reset an application that has since moved to interviewing."""
    service, repository = _log()

    logged = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )
    logged.change_status(ApplicationStatus.INTERVIEWING)
    await repository.update(logged)

    again = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )

    assert again.status is ApplicationStatus.INTERVIEWING


async def test_a_concurrent_log_of_the_same_submission_yields_one_record() -> None:
    """The race the unique constraint exists for: both callers pass the
    "already logged?" read, so one insert must lose and adopt the winner."""

    class RacingRepository(FakeTrackedApplicationRepository):
        """Reports "not logged" on the first read, as a concurrent request that
        has not committed yet would."""

        def __init__(self) -> None:
            super().__init__()
            self.reads = 0

        async def get_by_submission_key(
            self, *, user_id: str, submission_key: str
        ) -> TrackedApplication | None:
            self.reads += 1
            if self.reads == 1:
                return None
            return await super().get_by_submission_key(
                user_id=user_id, submission_key=submission_key
            )

    repository = RacingRepository()
    # The row the "other request" already committed.
    winner = TrackedApplication(
        id="tracked-winner",
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        company_name="Globex",
        role_title="Senior Backend Engineer",
        applied_at=_APPLIED_AT,
        resume_document_id="doc-resume",
    )
    repository.rows[winner.id] = winner

    service, _ = _log(applications=repository)

    logged = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=_SUBMISSION_KEY,
        applied_at=_APPLIED_AT,
    )

    assert logged.id == "tracked-winner"
    assert len(repository.rows) == 1
    # It really did attempt the insert and lose, rather than short-circuiting.
    assert repository.add_calls == 1


async def test_a_constraint_violation_with_nothing_readable_is_not_swallowed() -> None:
    """If the unique constraint fires but no row can be read back, that is not
    a race — it must surface rather than be reported as a successful log."""

    class AlwaysConflictingRepository(FakeTrackedApplicationRepository):
        async def add(self, application: TrackedApplication) -> None:
            raise ApplicationAlreadyLoggedError(
                user_id=application.user_id,
                submission_key=application.submission_key,
            )

    service, _ = _log(applications=AlwaysConflictingRepository())

    with pytest.raises(ApplicationAlreadyLoggedError):
        await service.record(
            user_id=_USER_ID,
            job_posting_id=_JOB_ID,
            submission_key=_SUBMISSION_KEY,
            applied_at=_APPLIED_AT,
        )


async def test_two_applications_to_one_posting_are_two_records() -> None:
    """Distinct submissions, so distinct keys — re-applying months later is a
    real second application, not a duplicate to be collapsed."""
    service, repository = _log()

    first = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key="review-1",
        applied_at=_APPLIED_AT,
    )
    second = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key="review-2",
        applied_at=datetime(2027, 1, 15, 9, 0, tzinfo=UTC),
    )

    assert first.id != second.id
    assert len(repository.rows) == 2


async def test_a_dangling_reference_is_not_mistaken_for_a_duplicate() -> None:
    """The two integrity failures have opposite remedies, so a reference error
    must propagate instead of being absorbed by the idempotent path."""

    class DanglingReferenceRepository(FakeTrackedApplicationRepository):
        async def add(self, application: TrackedApplication) -> None:
            raise TrackedApplicationReferenceError(
                job_posting_id=application.job_posting_id,
                resume_document_id=application.resume_document_id,
            )

    service, _ = _log(applications=DanglingReferenceRepository())

    with pytest.raises(TrackedApplicationReferenceError):
        await service.record(
            user_id=_USER_ID,
            job_posting_id=_JOB_ID,
            submission_key=_SUBMISSION_KEY,
            applied_at=_APPLIED_AT,
        )


async def test_another_candidates_snapshot_cannot_be_logged() -> None:
    """The domain's ownership check still applies when the log is the caller —
    a document store that returned the wrong user's resume is refused here."""
    foreign_resume = ApplicationDocument(
        id="doc-resume-foreign",
        user_id="someone-else",
        job_posting_id=_JOB_ID,
        document_kind=GeneratedDocumentKind.TAILORED_RESUME,
        content="EXPERIENCE\nSomeone else entirely",
        version=1,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )

    class LeakyDocumentRepository(FakeDocumentRepository):
        async def get_latest(
            self,
            *,
            user_id: str,
            job_posting_id: str,
            document_kind: GeneratedDocumentKind,
        ) -> ApplicationDocument | None:
            if document_kind is GeneratedDocumentKind.TAILORED_RESUME:
                return foreign_resume
            return None

    repository = FakeTrackedApplicationRepository()
    service = SubmittedApplicationLog(
        tracked_application_repository=repository,  # type: ignore[arg-type]
        document_repository=LeakyDocumentRepository(),  # type: ignore[arg-type]
        job_posting_repository=FakeJobPostingRepository(  # type: ignore[arg-type]
            [_posting()]
        ),
        id_generator=SequentialIdGenerator(),  # type: ignore[arg-type]
    )

    with pytest.raises(InvalidValueError, match="belongs to another candidate"):
        await service.record(
            user_id=_USER_ID,
            job_posting_id=_JOB_ID,
            submission_key=_SUBMISSION_KEY,
            applied_at=_APPLIED_AT,
        )

    assert repository.rows == {}
