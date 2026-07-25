"""Tests for the tracker logging wired into SubmitApplicationReview.

The submission flow's own rules (the blocker gate, the double-submit refusal)
are covered by `test_application_review_use_cases.py`. What is proved here is
the logging contract specifically:

- submitting logs one tracked application, against the exact stored snapshots;
- nothing is logged when the submission is refused;
- a failure to log never turns a successful submission into a failed one, and
  the failure is left replayable.

The last one is the reason this lives in its own file: it is the case where the
correct behaviour is to swallow an exception, which is worth stating explicitly
rather than burying in a suite about submission rules.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from src.application.dtos.application_review_dtos import SubmitApplicationReviewInput
from src.application.services.submitted_application_log import SubmittedApplicationLog
from src.application.use_cases.submit_application_review import SubmitApplicationReview
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.application_review import ApplicationReview
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.exceptions import BusinessRuleViolationError
from src.domain.value_objects.application_field_slot import ApplicationFieldSlot
from src.domain.value_objects.ats_provider import AtsProvider
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.reviewed_answer import AnswerOrigin, ReviewedAnswer
from tests.application.conftest import (
    InMemoryApplicationDocumentRepository,
    InMemoryApplicationReviewRepository,
    InMemoryPortalHandoffRepository,
    StubJobPostingRepository,
)
from tests.application.test_submitted_application_log import (
    FakeTrackedApplicationRepository,
    SequentialIdGenerator,
)

_USER_ID = "user-1"
_JOB_ID = "job-posting-1"
_APPLY_URL = "https://boards.greenhouse.io/globex/jobs/4001"


def _posting() -> JobPosting:
    return JobPosting(
        id=_JOB_ID,
        source="greenhouse",
        company="Globex",
        title="Senior Backend Engineer",
        apply_url=_APPLY_URL,
        description="Build the thing.",
    )


def _document(*, document_id: str, kind: GeneratedDocumentKind) -> ApplicationDocument:
    return ApplicationDocument(
        id=document_id,
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        document_kind=kind,
        content="EXPERIENCE\nBackend Engineer at Acme",
        version=1,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )


def _settled_review(review_id: str = "review-1") -> ApplicationReview:
    """A review with nothing outstanding, so `record_submission` will allow it.

    One plain answered field: no sensitive value needing confirmation, which is
    what a blocker would otherwise be.
    """
    return ApplicationReview(
        id=review_id,
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        apply_url=_APPLY_URL,
        ats_provider=AtsProvider.GREENHOUSE,
        answers=(
            ReviewedAnswer(
                key="first_name",
                label="First name",
                widget_kind="text",
                value="Dana",
                slot=ApplicationFieldSlot.FIRST_NAME,
                required=True,
                origin=AnswerOrigin.AUTOFILLED,
            ),
        ),
    )


def _build(
    *,
    review: ApplicationReview,
    documents: list[ApplicationDocument] | None = None,
    postings: JobPosting | None = None,
    handoffs: list[PortalHandoff] | None = None,
    tracked: FakeTrackedApplicationRepository | None = None,
    log: SubmittedApplicationLog | None = None,
) -> tuple[SubmitApplicationReview, FakeTrackedApplicationRepository]:
    tracked_repository = tracked or FakeTrackedApplicationRepository()
    if documents is None:
        documents = [
            _document(
                document_id="doc-resume", kind=GeneratedDocumentKind.TAILORED_RESUME
            ),
            _document(
                document_id="doc-letter", kind=GeneratedDocumentKind.COVER_LETTER
            ),
        ]
    service = log or SubmittedApplicationLog(
        tracked_application_repository=tracked_repository,  # type: ignore[arg-type]
        document_repository=InMemoryApplicationDocumentRepository(documents),
        job_posting_repository=StubJobPostingRepository(
            postings if postings is not None else _posting()
        ),
        id_generator=SequentialIdGenerator(),  # type: ignore[arg-type]
    )
    use_case = SubmitApplicationReview(
        review_repository=InMemoryApplicationReviewRepository([review]),
        handoff_repository=InMemoryPortalHandoffRepository(handoffs or []),
        submitted_application_log=service,
    )
    return use_case, tracked_repository


# ---- criterion 1: a record is logged on submission --------------------------


async def test_submitting_logs_a_tracked_application() -> None:
    review = _settled_review()
    use_case, tracked = _build(review=review)

    await use_case.execute(
        SubmitApplicationReviewInput(user_id=_USER_ID, review_id=review.id)
    )

    assert len(tracked.rows) == 1
    logged = next(iter(tracked.rows.values()))
    assert logged.user_id == _USER_ID
    assert logged.job_posting_id == _JOB_ID


# ---- criterion 2: the exact sent documents ----------------------------------


async def test_the_logged_record_links_the_exact_stored_snapshots() -> None:
    review = _settled_review()
    use_case, tracked = _build(review=review)

    await use_case.execute(
        SubmitApplicationReviewInput(user_id=_USER_ID, review_id=review.id)
    )

    logged = next(iter(tracked.rows.values()))
    assert logged.resume_document_id == "doc-resume"
    assert logged.cover_letter_document_id == "doc-letter"


# ---- criterion 3: role, company, date captured automatically -----------------


async def test_role_company_and_date_come_from_the_records_not_the_request() -> None:
    review = _settled_review()
    use_case, tracked = _build(review=review)

    output = await use_case.execute(
        SubmitApplicationReviewInput(user_id=_USER_ID, review_id=review.id)
    )

    logged = next(iter(tracked.rows.values()))
    assert logged.role_title == "Senior Backend Engineer"
    assert logged.company_name == "Globex"
    # The date is the submission time recorded on the review, not "now" as
    # observed separately by the tracker.
    assert logged.applied_at == output.review.submitted_at


# ---- criterion 4: idempotent, and never at the submission's expense ---------


async def test_the_submission_key_is_the_review_id() -> None:
    """What makes a replay idempotent: the key is the submission event, so
    logging the same review again cannot produce a second application."""
    review = _settled_review("review-xyz")
    use_case, tracked = _build(review=review)

    await use_case.execute(
        SubmitApplicationReviewInput(user_id=_USER_ID, review_id=review.id)
    )

    logged = next(iter(tracked.rows.values()))
    assert logged.submission_key == "review-xyz"


async def test_a_replay_of_the_same_submission_adds_no_second_record() -> None:
    """Stands in for the repair path: re-running the log for a submission that
    already logged is a no-op."""
    review = _settled_review()
    use_case, tracked = _build(review=review)

    await use_case.execute(
        SubmitApplicationReviewInput(user_id=_USER_ID, review_id=review.id)
    )
    logged = next(iter(tracked.rows.values()))

    # The same submission, logged again directly through the service.
    service = SubmittedApplicationLog(
        tracked_application_repository=tracked,  # type: ignore[arg-type]
        document_repository=InMemoryApplicationDocumentRepository(
            [
                _document(
                    document_id="doc-resume",
                    kind=GeneratedDocumentKind.TAILORED_RESUME,
                )
            ]
        ),
        job_posting_repository=StubJobPostingRepository(_posting()),
        id_generator=SequentialIdGenerator(),  # type: ignore[arg-type]
    )
    again = await service.record(
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        submission_key=review.id,
        applied_at=datetime(2027, 1, 1, tzinfo=UTC),
    )

    assert again.id == logged.id
    assert len(tracked.rows) == 1


async def test_a_refused_submission_logs_nothing() -> None:
    """An open hand-off blocks submitting, and a blocked submission is not an
    application — so nothing may reach the tracker."""
    review = _settled_review()
    handoff = PortalHandoff(
        id="handoff-1",
        user_id=_USER_ID,
        job_posting_id=_JOB_ID,
        apply_url=_APPLY_URL,
        paused_url=f"{_APPLY_URL}/login",
        hard_stops=(HardStop(kind=HardStopKind.ACCOUNT_WALL, evidence=("Sign in",)),),
    )
    use_case, tracked = _build(review=review, handoffs=[handoff])

    with pytest.raises(BusinessRuleViolationError):
        await use_case.execute(
            SubmitApplicationReviewInput(user_id=_USER_ID, review_id=review.id)
        )

    assert tracked.rows == {}


async def test_a_failure_to_log_does_not_fail_the_submission(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The candidate's application is with the employer either way. Reporting a
    failure here would tell them something false about it — and the domain
    refuses the retry that message would invite."""

    class BrokenLog(SubmittedApplicationLog):
        def __init__(self) -> None:  # no collaborators needed; it only fails
            pass

        async def record(self, **kwargs: object) -> TrackedApplication:
            raise RuntimeError("tracker database is unreachable")

    review = _settled_review()
    use_case, tracked = _build(review=review, log=BrokenLog())

    with caplog.at_level(logging.ERROR):
        output = await use_case.execute(
            SubmitApplicationReviewInput(user_id=_USER_ID, review_id=review.id)
        )

    # The submission succeeded and is recorded as submitted.
    assert output.review.submitted_at is not None
    assert output.apply_url == _APPLY_URL
    assert tracked.rows == {}
    # And it left behind what is needed to replay the log.
    assert "Failed to log a submitted application" in caplog.text
    assert review.id in caplog.text
    assert _JOB_ID in caplog.text


async def test_the_review_is_still_marked_submitted_when_logging_fails() -> None:
    """The ordering guarantee: the submission is persisted before the tracker is
    touched, so a tracker failure cannot lose the fact that they submitted."""

    class BrokenLog(SubmittedApplicationLog):
        def __init__(self) -> None:
            pass

        async def record(self, **kwargs: object) -> TrackedApplication:
            raise RuntimeError("tracker database is unreachable")

    review = _settled_review()
    review_repository = InMemoryApplicationReviewRepository([review])
    use_case = SubmitApplicationReview(
        review_repository=review_repository,
        handoff_repository=InMemoryPortalHandoffRepository([]),
        submitted_application_log=BrokenLog(),
    )

    await use_case.execute(
        SubmitApplicationReviewInput(user_id=_USER_ID, review_id=review.id)
    )

    stored = await review_repository.get_by_id(review.id)
    assert stored is not None
    assert stored.submitted_at is not None
    assert not stored.is_open
