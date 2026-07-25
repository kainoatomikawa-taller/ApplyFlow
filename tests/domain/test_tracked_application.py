"""Unit tests for the TrackedApplication entity — the tracker's spine.

The interesting cases here are the reference checks. A foreign key can prove
`resume_document_id` names *a* row in `application_documents`; only the domain
can prove it names the resume that went to *this* employer for *this*
candidate, and getting that wrong produces a tracker that confidently misstates
what was sent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.exceptions import BusinessRuleViolationError, InvalidValueError
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource

_USER_ID = "user-1"
_SUBMISSION_KEY = "review-1"


def _posting(posting_id: str = "job-1") -> JobPosting:
    return JobPosting(
        id=posting_id,
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
    user_id: str = _USER_ID,
    job_posting_id: str = "job-1",
) -> ApplicationDocument:
    return ApplicationDocument(
        id=document_id,
        user_id=user_id,
        job_posting_id=job_posting_id,
        document_kind=kind,
        content="EXPERIENCE\nBackend Engineer at Acme",
        version=1,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )


def _resume(**kwargs: object) -> ApplicationDocument:
    return _document(
        document_id="doc-resume",
        kind=GeneratedDocumentKind.TAILORED_RESUME,
        **kwargs,  # type: ignore[arg-type]
    )


def _letter(**kwargs: object) -> ApplicationDocument:
    return _document(
        document_id="doc-letter",
        kind=GeneratedDocumentKind.COVER_LETTER,
        **kwargs,  # type: ignore[arg-type]
    )


def _tracked(**overrides: object) -> TrackedApplication:
    defaults: dict[str, object] = {
        "id": "tracked-1",
        "user_id": _USER_ID,
        "job_posting_id": "job-1",
        "submission_key": _SUBMISSION_KEY,
        "company_name": "Globex",
        "role_title": "Senior Backend Engineer",
        "applied_at": datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        "resume_document_id": "doc-resume",
    }
    defaults.update(overrides)
    return TrackedApplication(**defaults)  # type: ignore[arg-type]


# ---- record_sent ------------------------------------------------------------


def test_record_sent_captures_role_company_date_status_and_job_reference() -> None:
    """Acceptance criterion 1, at the entity level."""
    posting = _posting()
    applied_at = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)

    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=posting,
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
        cover_letter_document=_letter(),
        applied_at=applied_at,
    )

    assert tracked.role_title == "Senior Backend Engineer"
    assert tracked.company_name == "Globex"
    assert tracked.applied_at == applied_at
    assert tracked.status is ApplicationStatus.APPLIED
    assert tracked.job_posting_id == posting.id


def test_record_sent_references_the_exact_stored_documents() -> None:
    """Acceptance criterion 2: ids of archived snapshots, not regenerated text."""
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=_posting(),
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
        cover_letter_document=_letter(),
    )

    assert tracked.resume_document_id == "doc-resume"
    assert tracked.cover_letter_document_id == "doc-letter"


def test_role_and_company_are_copied_not_read_through_the_posting() -> None:
    """A posting retitled after the fact must not rewrite the history of an
    application already sent."""
    posting = _posting()
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=posting,
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
    )

    posting.title = "Staff Backend Engineer"
    posting.company = "Globex International"

    assert tracked.role_title == "Senior Backend Engineer"
    assert tracked.company_name == "Globex"


def test_a_cover_letter_is_optional() -> None:
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=_posting(),
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
    )

    assert tracked.cover_letter_document_id is None


def test_applied_at_defaults_to_now_when_the_caller_does_not_say() -> None:
    before = datetime.now(UTC)
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=_posting(),
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
    )

    assert before - timedelta(seconds=5) <= tracked.applied_at
    assert tracked.applied_at <= datetime.now(UTC) + timedelta(seconds=5)


# ---- the reference checks a foreign key cannot make -------------------------


def test_a_cover_letter_cannot_be_recorded_as_the_resume() -> None:
    with pytest.raises(InvalidValueError, match="not a tailored resume"):
        TrackedApplication.record_sent(
            application_id="tracked-1",
            user_id=_USER_ID,
            job_posting=_posting(),
            submission_key=_SUBMISSION_KEY,
            resume_document=_letter(),
        )


def test_a_resume_cannot_be_recorded_as_the_cover_letter() -> None:
    with pytest.raises(InvalidValueError, match="not a cover letter"):
        TrackedApplication.record_sent(
            application_id="tracked-1",
            user_id=_USER_ID,
            job_posting=_posting(),
            submission_key=_SUBMISSION_KEY,
            resume_document=_resume(),
            cover_letter_document=_resume(),
        )


def test_another_jobs_resume_is_refused() -> None:
    """The failure this check exists for: a valid document id that has nothing
    to do with the application being filed."""
    with pytest.raises(InvalidValueError, match="was produced for job posting"):
        TrackedApplication.record_sent(
            application_id="tracked-1",
            user_id=_USER_ID,
            job_posting=_posting("job-1"),
            submission_key=_SUBMISSION_KEY,
            resume_document=_resume(job_posting_id="job-2"),
        )


def test_another_candidates_resume_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="belongs to another candidate"):
        TrackedApplication.record_sent(
            application_id="tracked-1",
            user_id=_USER_ID,
            job_posting=_posting(),
            submission_key=_SUBMISSION_KEY,
            resume_document=_resume(user_id="someone-else"),
        )


def test_another_jobs_cover_letter_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="was produced for job posting"):
        TrackedApplication.record_sent(
            application_id="tracked-1",
            user_id=_USER_ID,
            job_posting=_posting("job-1"),
            submission_key=_SUBMISSION_KEY,
            resume_document=_resume(),
            cover_letter_document=_letter(job_posting_id="job-2"),
        )


# ---- invariants -------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", ""),
        ("user_id", ""),
        ("job_posting_id", ""),
        ("company_name", "   "),
        ("role_title", "   "),
        ("resume_document_id", ""),
        ("submission_key", "   "),
    ],
)
def test_required_fields_are_rejected_when_empty(field: str, value: str) -> None:
    with pytest.raises(InvalidValueError):
        _tracked(**{field: value})


def test_the_submission_key_is_carried_through_record_sent() -> None:
    """It is the idempotency key, so it has to survive construction rather than
    being regenerated per attempt."""
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=_posting(),
        submission_key="review-abc",
        resume_document=_resume(),
    )

    assert tracked.submission_key == "review-abc"


def test_a_blank_cover_letter_reference_is_refused() -> None:
    """An empty string would read downstream as "there was a letter" and then
    resolve to nothing. None is the honest way to say there wasn't one."""
    with pytest.raises(InvalidValueError, match="cannot be blank"):
        _tracked(cover_letter_document_id="")


def test_a_tracked_application_cannot_be_a_draft() -> None:
    """DRAFT belongs to ApplicationReview — this record exists because the
    application was sent, so `applied_at` would name a date on which nothing
    happened."""
    with pytest.raises(InvalidValueError, match="cannot be in 'draft'"):
        _tracked(status=ApplicationStatus.DRAFT)


def test_a_naive_applied_at_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="timezone-aware"):
        _tracked(applied_at=datetime(2026, 7, 25, 12, 0))


# ---- lifecycle --------------------------------------------------------------


def test_status_transitions_follow_the_shared_state_machine() -> None:
    tracked = _tracked()

    tracked.change_status(ApplicationStatus.INTERVIEWING)
    assert tracked.status is ApplicationStatus.INTERVIEWING

    tracked.change_status(ApplicationStatus.OFFER)
    assert tracked.status is ApplicationStatus.OFFER


def test_an_invalid_transition_is_refused_by_the_state_machine() -> None:
    tracked = _tracked(status=ApplicationStatus.REJECTED)

    with pytest.raises(BusinessRuleViolationError):
        tracked.change_status(ApplicationStatus.INTERVIEWING)


def test_a_status_change_touches_updated_at() -> None:
    tracked = _tracked()
    before = tracked.updated_at

    tracked.change_status(ApplicationStatus.INTERVIEWING)

    assert tracked.updated_at >= before


def test_is_open_tracks_whether_the_application_is_still_live() -> None:
    assert _tracked().is_open is True
    assert _tracked(status=ApplicationStatus.INTERVIEWING).is_open is True
    assert _tracked(status=ApplicationStatus.REJECTED).is_open is False
    assert _tracked(status=ApplicationStatus.WITHDRAWN).is_open is False


# ---- attaching a letter after the fact --------------------------------------


def test_a_cover_letter_can_be_attached_after_the_row_exists() -> None:
    tracked = _tracked()

    tracked.attach_cover_letter(_letter())

    assert tracked.cover_letter_document_id == "doc-letter"


def test_an_already_referenced_cover_letter_cannot_be_swapped() -> None:
    """The reference states what the employer received; repointing it would
    rewrite what was sent."""
    tracked = _tracked(cover_letter_document_id="doc-letter")

    with pytest.raises(InvalidValueError, match="already references"):
        tracked.attach_cover_letter(
            _document(
                document_id="doc-letter-2", kind=GeneratedDocumentKind.COVER_LETTER
            )
        )


def test_attaching_another_jobs_cover_letter_is_refused() -> None:
    tracked = _tracked()

    with pytest.raises(InvalidValueError, match="was produced for job posting"):
        tracked.attach_cover_letter(_letter(job_posting_id="job-2"))


def test_attaching_a_resume_as_the_cover_letter_is_refused() -> None:
    tracked = _tracked()

    with pytest.raises(InvalidValueError, match="not a cover letter"):
        tracked.attach_cover_letter(_resume())
