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
from src.domain.value_objects.application_status_change import ApplicationStatusChange
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource

_USER_ID = "user-1"
_SUBMISSION_KEY = "review-1"


def _posting(posting_id: str = "job-1", location: str | None = None) -> JobPosting:
    return JobPosting(
        id=posting_id,
        source="greenhouse",
        company="Globex",
        title="Senior Backend Engineer",
        apply_url="https://boards.greenhouse.io/globex/jobs/1",
        description="Build the thing.",
        location=location,
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


# ---- status history ---------------------------------------------------------
#
# The property under test throughout: an application's current status and its
# history are two views of one fact, and the entity does not allow them to
# disagree. Every case below is one way they could.


def test_a_new_application_starts_with_the_entry_for_being_sent() -> None:
    """History is never empty, and never invented: the first entry is the
    application being sent, dated when it was sent, with nothing before it."""
    tracked = _tracked()

    (initial,) = tracked.status_history
    assert initial.status is ApplicationStatus.APPLIED
    assert initial.previous_status is None
    assert initial.is_initial
    assert initial.changed_at == tracked.applied_at
    assert tracked.current_status_since == tracked.applied_at


def test_each_change_appends_an_entry_naming_where_it_came_from() -> None:
    tracked = _tracked()

    tracked.change_status(ApplicationStatus.INTERVIEWING)
    tracked.change_status(ApplicationStatus.OFFER)

    assert [entry.status for entry in tracked.status_history] == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFER,
    ]
    assert [entry.previous_status for entry in tracked.status_history] == [
        None,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEWING,
    ]


def test_change_status_returns_the_entry_it_recorded() -> None:
    """So a caller can report or log the transition without re-reading the
    history to work out which entry was just added."""
    tracked = _tracked()

    change = tracked.change_status(ApplicationStatus.INTERVIEWING, note="phone screen")

    assert change is tracked.last_status_change
    assert change.previous_status is ApplicationStatus.APPLIED
    assert change.note == "phone screen"


def test_a_refused_transition_records_nothing() -> None:
    """The history is evidence. A move that was refused did not happen, so it
    must leave no trace — including no note."""
    tracked = _tracked(status=ApplicationStatus.REJECTED)
    before = list(tracked.status_history)

    with pytest.raises(BusinessRuleViolationError):
        tracked.change_status(ApplicationStatus.INTERVIEWING, note="hoping")

    assert tracked.status_history == before
    assert tracked.status is ApplicationStatus.REJECTED


def test_moving_to_the_status_it_already_holds_is_refused() -> None:
    """Otherwise "how long has it been at this status?" would have two
    answers."""
    tracked = _tracked()

    with pytest.raises(BusinessRuleViolationError):
        tracked.change_status(ApplicationStatus.APPLIED)


def test_current_status_since_moves_with_the_status() -> None:
    """`applied_at` cannot express "interviewing since Tuesday", which is the
    field a follow-up view actually sorts on."""
    tracked = _tracked()
    interviewing_at = tracked.applied_at + timedelta(days=9)

    tracked.change_status(ApplicationStatus.INTERVIEWING, changed_at=interviewing_at)

    assert tracked.current_status_since == interviewing_at
    assert tracked.applied_at != interviewing_at


def test_a_change_cannot_be_recorded_before_the_one_it_follows() -> None:
    tracked = _tracked()
    tracked.change_status(
        ApplicationStatus.INTERVIEWING,
        changed_at=tracked.applied_at + timedelta(days=5),
    )

    with pytest.raises(InvalidValueError, match="cannot be recorded earlier"):
        tracked.change_status(
            ApplicationStatus.OFFER,
            changed_at=tracked.applied_at + timedelta(days=1),
        )


def test_has_held_status_reads_the_history_not_the_current_status() -> None:
    """An application rejected after two rounds did interview. Counting it as
    never having interviewed would understate every funnel it appears in."""
    tracked = _tracked()
    tracked.change_status(ApplicationStatus.INTERVIEWING)
    tracked.change_status(ApplicationStatus.REJECTED)

    assert tracked.status is ApplicationStatus.REJECTED
    assert tracked.has_held_status(ApplicationStatus.INTERVIEWING)
    assert not tracked.has_held_status(ApplicationStatus.OFFER)


def test_reaching_a_terminal_status_closes_the_application() -> None:
    tracked = _tracked()
    assert tracked.is_open

    tracked.change_status(ApplicationStatus.WITHDRAWN)

    assert not tracked.is_open


# ---- reconstruction from storage --------------------------------------------


def _change(
    status: ApplicationStatus,
    *,
    previous: ApplicationStatus | None = None,
    day: int = 25,
) -> ApplicationStatusChange:
    return ApplicationStatusChange(
        status=status,
        changed_at=datetime(2026, 7, day, 12, 0, tzinfo=UTC),
        previous_status=previous,
    )


def test_a_stored_history_is_loaded_as_given() -> None:
    tracked = _tracked(
        status=ApplicationStatus.INTERVIEWING,
        status_history=[
            _change(ApplicationStatus.APPLIED, day=25),
            _change(
                ApplicationStatus.INTERVIEWING,
                previous=ApplicationStatus.APPLIED,
                day=28,
            ),
        ],
    )

    assert len(tracked.status_history) == 2
    assert tracked.current_status_since == datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def test_a_row_predating_history_tracking_is_seeded_rather_than_rejected() -> None:
    """A row that knows its status and when it was sent *is* a one-entry
    history, so it loads as one — that is what makes the backfill honest
    instead of guesswork."""
    tracked = _tracked(status=ApplicationStatus.REJECTED, status_history=[])

    (only,) = tracked.status_history
    assert only.status is ApplicationStatus.REJECTED
    assert only.is_initial
    assert only.changed_at == tracked.applied_at


def test_a_history_that_disagrees_with_the_status_is_refused() -> None:
    """The invariant the aggregate exists to keep. A row like this is one two
    different queries would answer differently."""
    with pytest.raises(InvalidValueError, match="history arrived at"):
        _tracked(
            status=ApplicationStatus.OFFER,
            status_history=[_change(ApplicationStatus.APPLIED)],
        )


def test_a_history_that_does_not_start_at_the_beginning_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="must begin with the entry"):
        _tracked(
            status=ApplicationStatus.INTERVIEWING,
            status_history=[
                _change(
                    ApplicationStatus.INTERVIEWING, previous=ApplicationStatus.APPLIED
                )
            ],
        )


def test_a_history_with_two_beginnings_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="only have one"):
        _tracked(
            status=ApplicationStatus.INTERVIEWING,
            status_history=[
                _change(ApplicationStatus.APPLIED),
                _change(ApplicationStatus.INTERVIEWING),
            ],
        )


def test_a_history_whose_chain_is_broken_is_refused() -> None:
    """`previous_status` is redundant with the preceding entry on purpose: it
    is what makes a corrupt history detectable rather than merely wrong."""
    with pytest.raises(InvalidValueError, match="inconsistent"):
        _tracked(
            status=ApplicationStatus.OFFER,
            status_history=[
                _change(ApplicationStatus.APPLIED),
                _change(
                    ApplicationStatus.OFFER, previous=ApplicationStatus.INTERVIEWING
                ),
            ],
        )


def test_a_history_that_runs_backwards_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="oldest first"):
        _tracked(
            status=ApplicationStatus.INTERVIEWING,
            status_history=[
                _change(ApplicationStatus.APPLIED, day=28),
                _change(
                    ApplicationStatus.INTERVIEWING,
                    previous=ApplicationStatus.APPLIED,
                    day=25,
                ),
            ],
        )


def test_record_sent_produces_an_application_with_its_first_entry() -> None:
    tracked = TrackedApplication.record_sent(
        application_id="tracked-9",
        user_id=_USER_ID,
        job_posting=_posting(),
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
    )

    (initial,) = tracked.status_history
    assert initial.status is ApplicationStatus.APPLIED
    assert initial.changed_at == tracked.applied_at

# ---- canonical identity (what matching suppresses on) -----------------------


def test_record_sent_snapshots_the_postings_location() -> None:
    """The third component of the role identity, copied like role and company
    so the answer survives the posting being pruned or relisted."""
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=_posting(location="Berlin, DE"),
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
    )

    assert tracked.job_location == "Berlin, DE"


def test_a_posting_naming_no_location_records_none() -> None:
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=_posting(),
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
    )

    assert tracked.job_location is None


def test_the_recorded_identity_is_the_postings_identity() -> None:
    """What ties the tracker to the matching layer: an application recorded
    against a posting must produce the identity that posting matches on."""
    posting = _posting(location="Berlin, DE")
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=posting,
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
    )

    assert tracked.canonical_identity == posting.canonical_identity


def test_the_identity_survives_the_posting_being_retitled() -> None:
    """The snapshot is the point: a posting edited after the fact must not
    change which role the candidate is recorded as having applied to."""
    posting = _posting(location="Berlin, DE")
    tracked = TrackedApplication.record_sent(
        application_id="tracked-1",
        user_id=_USER_ID,
        job_posting=posting,
        submission_key=_SUBMISSION_KEY,
        resume_document=_resume(),
    )
    before = tracked.canonical_identity

    posting.title = "Staff Backend Engineer"
    posting.location = "Munich, DE"

    assert tracked.canonical_identity == before


def test_the_recorded_identity_is_normalized() -> None:
    tracked = _tracked(
        company_name="  GLOBEX  ",
        role_title="Senior  Backend Engineer",
        job_location=" Berlin, DE ",
    )

    identity = tracked.canonical_identity
    assert identity.company == "globex"
    assert identity.title == "senior backend engineer"
    assert identity.location == "berlin, de"
