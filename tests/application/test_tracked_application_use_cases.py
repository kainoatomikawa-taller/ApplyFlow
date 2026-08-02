"""Tests for the tracker's two use cases: reading the feed, and following an
application through its lifecycle (Epic 06).

The property most of these exist to protect is the same one the entity does:
the tracker shows the document the employer received, never a newer one that
happens to be lying around.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.dtos.tracked_application_dtos import (
    ListTrackedApplicationsInput,
    UpdateTrackedApplicationStatusInput,
)
from src.application.use_cases.list_tracked_applications import (
    ListTrackedApplications,
)
from src.application.use_cases.update_tracked_application_status import (
    UpdateTrackedApplicationStatus,
)
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    TrackedApplicationNotFoundError,
)
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from tests.application.conftest import (
    InMemoryApplicationDocumentRepository,
    InMemoryTrackedApplicationRepository,
)

USER = "user-1"
APPLIED_AT = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)


def posting(
    posting_id: str = "job-1",
    *,
    company: str = "Globex",
    title: str = "Senior Platform Engineer",
    location: str | None = "Austin, TX",
) -> JobPosting:
    return JobPosting(
        id=posting_id,
        source="greenhouse",
        company=company,
        title=title,
        apply_url=f"https://boards.greenhouse.io/globex/jobs/{posting_id}",
        description="Platform role.",
        location=location,
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
    job_posting: JobPosting | None = None,
    resume: ApplicationDocument,
    cover_letter: ApplicationDocument | None = None,
    applied_at: datetime = APPLIED_AT,
    user_id: str = USER,
) -> TrackedApplication:
    return TrackedApplication.record_sent(
        application_id=application_id,
        user_id=user_id,
        job_posting=job_posting or posting(),
        submission_key=f"review-{application_id}",
        resume_document=resume,
        cover_letter_document=cover_letter,
        applied_at=applied_at,
    )


def build_list(applications, documents):
    return ListTrackedApplications(
        tracked_application_repository=InMemoryTrackedApplicationRepository(
            applications
        ),
        document_repository=InMemoryApplicationDocumentRepository(documents),
    )


def build_update(applications, documents):
    tracker = InMemoryTrackedApplicationRepository(applications)
    use_case = UpdateTrackedApplicationStatus(
        tracked_application_repository=tracker,
        document_repository=InMemoryApplicationDocumentRepository(documents),
    )
    return use_case, tracker


# ---- reading the feed --------------------------------------------------------


async def test_a_logged_application_comes_back_with_the_documents_it_was_sent_with():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    letter = document("doc-letter", GeneratedDocumentKind.COVER_LETTER)
    use_case = build_list(
        [tracked(resume=resume, cover_letter=letter)], [resume, letter]
    )

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.company_name == "Globex"
    assert row.role_title == "Senior Platform Engineer"
    assert row.applied_at == APPLIED_AT
    assert row.status == "applied"
    assert row.resume is not None and row.resume.id == "doc-resume"
    assert row.cover_letter is not None and row.cover_letter.id == "doc-letter"


async def test_the_resume_shown_is_the_one_that_was_sent_not_the_newest_one():
    """The whole point of the tracker referencing snapshots by id. A candidate
    who revises their resume after applying has a newer version stored for the
    same job; showing it would restate what the employer received."""
    sent = document("doc-resume-v1", GeneratedDocumentKind.TAILORED_RESUME, version=1)
    revised_later = document(
        "doc-resume-v2",
        GeneratedDocumentKind.TAILORED_RESUME,
        version=2,
        content="DANA REYES\nEXPERIENCE\n... (rewritten)",
    )
    use_case = build_list([tracked(resume=sent)], [sent, revised_later])

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.resume is not None
    assert row.resume.id == "doc-resume-v1"
    assert row.resume.version == 1


async def test_the_feed_carries_the_digest_but_never_the_document_text():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case = build_list([tracked(resume=resume)], [resume])

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.resume is not None
    assert row.resume.content_sha256 == resume.content_sha256
    assert not hasattr(row.resume, "content")


async def test_an_application_sent_without_a_cover_letter_reports_none():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case = build_list([tracked(resume=resume)], [resume])

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.cover_letter is None


async def test_applications_come_back_most_recently_applied_first():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    older = tracked("app-old", resume=resume, applied_at=APPLIED_AT - timedelta(days=9))
    newer = tracked("app-new", resume=resume, applied_at=APPLIED_AT)
    use_case = build_list([older, newer], [resume])

    rows = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert [row.id for row in rows] == ["app-new", "app-old"]


async def test_another_candidates_applications_are_not_in_the_feed():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    theirs = document(
        "doc-theirs", GeneratedDocumentKind.TAILORED_RESUME, job_posting_id="job-2"
    )
    object.__setattr__(theirs, "user_id", "user-2")
    mine = tracked("app-mine", resume=resume)
    use_case = build_list([mine], [resume, theirs])

    rows = await use_case.execute(ListTrackedApplicationsInput(user_id="user-2"))

    assert rows == []


async def test_a_reference_that_no_longer_resolves_still_reports_the_application():
    """A broken reference means the record of *what* was sent is gone. That
    the candidate applied at all is a separate fact, and the one suppression
    depends on — so the row appears, with an empty document reference."""
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case = build_list([tracked(resume=resume)], [])  # no documents stored

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.id == "app-1"
    assert row.company_name == "Globex"
    assert row.resume is None


async def test_the_status_choices_offered_are_the_domains_own():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case = build_list([tracked(resume=resume)], [resume])

    (row,) = await use_case.execute(ListTrackedApplicationsInput(user_id=USER))

    assert row.allowed_next_statuses == [
        status.value for status in ApplicationStatus.APPLIED.allowed_transitions
    ]
    assert row.is_open is True


async def test_the_limit_is_honoured():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    applications = [
        tracked(f"app-{n}", resume=resume, applied_at=APPLIED_AT - timedelta(days=n))
        for n in range(5)
    ]
    use_case = build_list(applications, [resume])

    rows = await use_case.execute(ListTrackedApplicationsInput(user_id=USER, limit=2))

    assert len(rows) == 2


# ---- updating a status -------------------------------------------------------


async def test_a_status_change_is_persisted_and_returned():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case, tracker = build_update([tracked(resume=resume)], [resume])

    output = await use_case.execute(
        UpdateTrackedApplicationStatusInput(
            user_id=USER, application_id="app-1", status="interviewing"
        )
    )

    assert output.status == "interviewing"
    assert tracker.rows["app-1"].status is ApplicationStatus.INTERVIEWING


async def test_the_updated_record_carries_the_next_set_of_choices():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case, _ = build_update([tracked(resume=resume)], [resume])

    output = await use_case.execute(
        UpdateTrackedApplicationStatusInput(
            user_id=USER, application_id="app-1", status="interviewing"
        )
    )

    assert output.allowed_next_statuses == ["offer", "rejected", "withdrawn"]


async def test_a_terminal_status_closes_the_application_and_offers_nothing_further():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case, _ = build_update([tracked(resume=resume)], [resume])

    output = await use_case.execute(
        UpdateTrackedApplicationStatusInput(
            user_id=USER, application_id="app-1", status="rejected"
        )
    )

    assert output.is_open is False
    assert output.allowed_next_statuses == []


async def test_a_transition_the_lifecycle_forbids_is_refused_and_nothing_is_written():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    application = tracked(resume=resume)
    application.change_status(ApplicationStatus.REJECTED)
    use_case, tracker = build_update([application], [resume])

    with pytest.raises(BusinessRuleViolationError):
        await use_case.execute(
            UpdateTrackedApplicationStatusInput(
                user_id=USER, application_id="app-1", status="interviewing"
            )
        )

    assert tracker.rows["app-1"].status is ApplicationStatus.REJECTED


async def test_a_sent_application_cannot_be_turned_back_into_a_draft():
    """`draft` is a real `ApplicationStatus`, and this record still cannot
    hold one: it exists because something was sent."""
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case, tracker = build_update([tracked(resume=resume)], [resume])

    with pytest.raises(BusinessRuleViolationError):
        await use_case.execute(
            UpdateTrackedApplicationStatusInput(
                user_id=USER, application_id="app-1", status="draft"
            )
        )

    assert tracker.rows["app-1"].status is ApplicationStatus.APPLIED


async def test_a_value_that_is_not_a_status_is_rejected():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    use_case, _ = build_update([tracked(resume=resume)], [resume])

    with pytest.raises(InvalidValueError) as caught:
        await use_case.execute(
            UpdateTrackedApplicationStatusInput(
                user_id=USER, application_id="app-1", status="ghosted"
            )
        )

    # The message names what was expected, so a caller can correct it.
    assert "interviewing" in str(caught.value)


async def test_an_unknown_application_is_not_found():
    use_case, _ = build_update([], [])

    with pytest.raises(TrackedApplicationNotFoundError):
        await use_case.execute(
            UpdateTrackedApplicationStatusInput(
                user_id=USER, application_id="app-nope", status="offer"
            )
        )


async def test_another_candidates_application_is_not_found_rather_than_forbidden():
    """Indistinguishable on purpose: a distinct "not yours" would confirm that
    an id the caller was handed is real."""
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    theirs = tracked(resume=resume, user_id=USER)
    use_case, tracker = build_update([theirs], [resume])

    with pytest.raises(TrackedApplicationNotFoundError):
        await use_case.execute(
            UpdateTrackedApplicationStatusInput(
                user_id="someone-else", application_id="app-1", status="rejected"
            )
        )

    assert tracker.rows["app-1"].status is ApplicationStatus.APPLIED


async def test_a_status_change_never_repoints_the_documents_that_were_sent():
    resume = document("doc-resume", GeneratedDocumentKind.TAILORED_RESUME)
    newer = document("doc-resume-v2", GeneratedDocumentKind.TAILORED_RESUME, version=2)
    use_case, tracker = build_update([tracked(resume=resume)], [resume, newer])

    output = await use_case.execute(
        UpdateTrackedApplicationStatusInput(
            user_id=USER, application_id="app-1", status="interviewing"
        )
    )

    assert output.resume is not None and output.resume.id == "doc-resume"
    assert tracker.rows["app-1"].resume_document_id == "doc-resume"
