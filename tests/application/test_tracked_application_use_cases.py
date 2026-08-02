"""Tests for what the tracker's reads say about the *documents* that went out.

The status lifecycle — transitions, history, the filters, ownership — is
covered by `test_application_status_tracking.py`, which drives the same four
use cases. This file covers the other half of what a tracked application has
to be able to answer, and the property it exists to protect is the one the
entity does: the tracker shows the document the employer received, never a
newer one that happens to be lying around.

Every read is exercised, because the failure this guards against is a *single*
path quietly resolving documents the other way.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.dtos.tracked_application_dtos import (
    GetTrackedApplicationInput,
    ListApplicationsForJobInput,
    ListTrackedApplicationsInput,
    UpdateApplicationStatusInput,
)
from src.application.use_cases.get_tracked_application import GetTrackedApplication
from src.application.use_cases.list_applications_for_job import ListApplicationsForJob
from src.application.use_cases.list_tracked_applications import ListTrackedApplications
from src.application.use_cases.update_application_status import UpdateApplicationStatus
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from tests.application.conftest import (
    InMemoryApplicationDocumentRepository,
    InMemoryTrackedApplicationRepository,
)

pytestmark = pytest.mark.asyncio

USER = "user-1"
APPLIED_AT = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)


def posting(posting_id: str = "job-1") -> JobPosting:
    return JobPosting(
        id=posting_id,
        source="greenhouse",
        company="Globex",
        title="Senior Platform Engineer",
        apply_url=f"https://boards.greenhouse.io/globex/jobs/{posting_id}",
        description="Platform role.",
        location="Austin, TX",
    )


def document(
    document_id: str,
    kind: GeneratedDocumentKind,
    *,
    job_posting_id: str = "job-1",
    version: int = 1,
    content: str = "DANA REYES\nEXPERIENCE\n...",
) -> ApplicationDocument:
    return ApplicationDocument(
        id=document_id,
        user_id=USER,
        job_posting_id=job_posting_id,
        document_kind=kind,
        content=content,
        version=version,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )


def tracked(
    application_id: str = "app-1",
    *,
    resume: ApplicationDocument,
    cover_letter: ApplicationDocument | None = None,
    applied_at: datetime = APPLIED_AT,
    user_id: str = USER,
) -> TrackedApplication:
    return TrackedApplication.record_sent(
        application_id=application_id,
        user_id=user_id,
        job_posting=posting(),
        submission_key=f"review-{application_id}",
        resume_document=resume,
        cover_letter_document=cover_letter,
        applied_at=applied_at,
    )


def stores(applications, documents):
    return (
        InMemoryTrackedApplicationRepository(applications),
        InMemoryApplicationDocumentRepository(documents),
    )


# ---- the feed ----------------------------------------------------------------


async def test_a_logged_application_comes_back_with_the_documents_it_was_sent_with():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    letter = document("doc-letter", GeneratedDocumentKind.COVER_LETTER)
    tracker, docs = stores(
        [tracked(resume=resume, cover_letter=letter)], [resume, letter]
    )
    use_case = ListTrackedApplications(tracker, docs)

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.company_name == "Globex"
    assert row.job_location == "Austin, TX"
    assert row.resume is not None and row.resume.id == "doc-resume"
    assert row.cover_letter is not None and row.cover_letter.id == "doc-letter"
    # The raw references are still on the row alongside the resolved ones.
    assert row.resume_document_id == "doc-resume"


async def test_the_resume_shown_is_the_one_that_was_sent_not_the_newest_one():
    """The whole point of the tracker referencing snapshots by id, and the one
    assertion that fails if a read is ever switched to `get_latest`. A
    candidate who revises their resume after applying has a newer version
    stored for the same job; showing it would restate what the employer
    received."""
    sent = document("doc-resume-v1", GeneratedDocumentKind.TAILORED_RESUME, version=1)
    revised_later = document(
        "doc-resume-v2",
        GeneratedDocumentKind.TAILORED_RESUME,
        version=2,
        content="DANA REYES\nEXPERIENCE\n... (rewritten)",
    )
    tracker, docs = stores([tracked(resume=sent)], [sent, revised_later])
    use_case = ListTrackedApplications(tracker, docs)

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.resume is not None
    assert row.resume.id == "doc-resume-v1"
    assert row.resume.version == 1


async def test_the_feed_carries_the_digest_but_never_the_document_text():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    tracker, docs = stores([tracked(resume=resume)], [resume])
    use_case = ListTrackedApplications(tracker, docs)

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.resume is not None
    assert row.resume.content_sha256 == resume.content_sha256
    assert not hasattr(row.resume, "content")


async def test_an_application_sent_without_a_cover_letter_reports_none():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    tracker, docs = stores([tracked(resume=resume)], [resume])
    use_case = ListTrackedApplications(tracker, docs)

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.cover_letter is None
    assert row.cover_letter_document_id is None


async def test_a_reference_that_no_longer_resolves_still_reports_the_application():
    """A broken reference means the record of *what* was sent is gone. That the
    candidate applied at all is a separate fact, and the one suppression
    depends on — so the row appears, with an empty document reference."""
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    tracker, docs = stores([tracked(resume=resume)], [])  # no documents stored
    use_case = ListTrackedApplications(tracker, docs)

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.id == "app-1"
    assert row.company_name == "Globex"
    assert row.resume is None
    # Still nameable, which is what makes the breakage diagnosable.
    assert row.resume_document_id == "doc-resume"


async def test_one_document_is_read_once_however_many_rows_reference_it():
    """Re-applying to a role means several rows pointing at the same snapshots,
    and a feed that re-read them per row would scale with history rather than
    with distinct documents."""
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    applications = [
        tracked("app-1", resume=resume),
        tracked("app-2", resume=resume),
        tracked("app-3", resume=resume),
    ]
    tracker, docs = stores(applications, [resume])
    reads: list[str] = []
    original = docs.get_by_id

    async def counting(document_id: str):
        reads.append(document_id)
        return await original(document_id)

    docs.get_by_id = counting  # type: ignore[method-assign]

    rows = await ListTrackedApplications(tracker, docs).execute(
        ListTrackedApplicationsInput(user_id=USER)
    )

    assert len(rows) == 3
    assert reads == ["doc-resume"]


async def test_the_status_choices_offered_are_the_domains_own():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    tracker, docs = stores([tracked(resume=resume)], [resume])

    (row,) = await ListTrackedApplications(tracker, docs).execute(
        ListTrackedApplicationsInput(user_id=USER)
    )

    assert row.allowed_next_statuses == [
        status.value for status in ApplicationStatus.APPLIED.allowed_transitions
    ]
    assert row.is_open is True


# ---- the other three reads ---------------------------------------------------


async def test_reading_one_application_resolves_its_documents_too():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    tracker, docs = stores([tracked(resume=resume)], [resume])

    output = await GetTrackedApplication(tracker, docs).execute(
        GetTrackedApplicationInput(user_id=USER, application_id="app-1")
    )

    assert output.resume is not None and output.resume.id == "doc-resume"


async def test_listing_one_postings_applications_resolves_their_documents_too():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    tracker, docs = stores([tracked(resume=resume)], [resume])

    (row,) = await ListApplicationsForJob(tracker, docs).execute(
        ListApplicationsForJobInput(user_id=USER, job_posting_id="job-1")
    )

    assert row.resume is not None and row.resume.id == "doc-resume"


async def test_a_status_change_returns_the_documents_and_never_repoints_them():
    """The screen that made the change re-renders from what came back, so the
    response has to carry them — and the change must not be able to move them
    onto a newer version that exists for the same job."""
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    newer = document("doc-resume-v2", GeneratedDocumentKind.TAILORED_RESUME, version=2)
    tracker, docs = stores([tracked(resume=resume)], [resume, newer])

    output = await UpdateApplicationStatus(tracker, docs).execute(
        UpdateApplicationStatusInput(
            user_id=USER, application_id="app-1", status="interviewing"
        )
    )

    assert output.status == "interviewing"
    assert output.resume is not None and output.resume.id == "doc-resume"
    assert output.allowed_next_statuses == ["offer", "rejected", "withdrawn"]
    assert tracker.rows["app-1"].resume_document_id == "doc-resume"
