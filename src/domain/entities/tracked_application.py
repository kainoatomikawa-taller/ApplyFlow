"""TrackedApplication entity — the spine of the tracker (Epic 06).

What it is
----------
One row per application the candidate actually sent: which role, at which
company, on which date, where it stands now, the job posting it came from,
and — the part that matters most — the *exact* resume and cover letter that
went out with it.

Why it is a separate aggregate from `ApplicationReview`
------------------------------------------------------
`ApplicationReview` is the working surface for an application *in flight*: a
form filled in a browser, answers the candidate is still editing, one open
review per posting. This entity is what remains once that application has been
sent. The split is deliberate — a tracker that also held drafts would have to
answer "when did you apply?" with `NULL` for half its rows, and every reader
would then carry a branch for applications that were never applications.

So a tracked application exists *because* something was sent:
`applied_at` is required and `DRAFT` is refused (see `__post_init__`). The
in-flight state already has a home, and it is not this table.

Why it points at documents instead of holding them
--------------------------------------------------
`resume_document_id` and `cover_letter_document_id` reference stored
`ApplicationDocument` snapshots (Epic 04). They are ids, not text, and that is
the whole point of the ticket: the tracker has to show the document the
employer received, and the only way to be sure of that is to name the snapshot
that was archived at send time. Regenerating one reads today's profile through
today's model and can quietly produce a document the employer never saw — see
`ApplicationDocument` for the full argument. A `TEXT` column here would be the
same mistake one layer up: a second copy of the letter, free to drift from the
snapshot that is supposed to be authoritative.

`record_sent` is where that reference is checked rather than trusted. It takes
the snapshot entities and verifies each one is the right *kind* and belongs to
this candidate and this posting, because "the wrong job's resume" is a
reference no foreign key can catch: `application_documents.id` is a valid
target whether or not the row behind it has anything to do with this
application.

Why role and company are stored, not read through the posting
------------------------------------------------------------
They are copied from `JobPosting` at record time. A posting is a live row —
re-ingested, re-normalized, retitled by the employer, eventually marked
stale — while this row states what the candidate applied to *then*. Deriving
the label on every read would let a posting edited in June rewrite the history
of an application sent in March. `record_sent` copies them from the posting so
the two cannot disagree at the moment it matters.

Not sensitive. A role title, a company name, and a status carry nothing that
`WorkAuthorization` or `AnswerMemory` do; the sensitive material lives in the
documents this row references, behind their own flags. So this entity is safe
to log — and logging it is the reason its document fields are ids.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.application_status import ApplicationStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class TrackedApplication:
    """One application the candidate sent, tracked through its lifecycle."""

    id: str
    user_id: str
    #: The source job record this application was made against.
    job_posting_id: str
    #: Copied from the posting at record time — see the module docstring.
    company_name: str
    role_title: str
    #: When the application was sent. Required: this row exists because it
    #: was. Timezone-aware, so applications ordered across a DST change or a
    #: deploy in another region still order correctly.
    applied_at: datetime
    #: The archived `ApplicationDocument` that went out as the resume.
    #: Required — an application ApplyFlow sent always carried one.
    resume_document_id: str
    #: The archived cover letter, when the posting asked for one. Optional
    #: because plenty of forms do not, and a fabricated reference would be
    #: worse than an honest absence.
    cover_letter_document_id: str | None = None
    status: ApplicationStatus = ApplicationStatus.APPLIED
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("TrackedApplication requires a non-empty id.")
        if not self.user_id:
            raise InvalidValueError("TrackedApplication requires a non-empty user_id.")
        if not self.job_posting_id:
            raise InvalidValueError(
                "TrackedApplication requires a non-empty job_posting_id — a "
                "tracked application always links back to the job it was for."
            )
        if not self.company_name.strip():
            raise InvalidValueError("TrackedApplication.company_name cannot be empty.")
        if not self.role_title.strip():
            raise InvalidValueError("TrackedApplication.role_title cannot be empty.")
        if not self.resume_document_id:
            raise InvalidValueError(
                "TrackedApplication requires a resume_document_id — the tracker "
                "records the resume that was sent, never one to be produced later."
            )
        # An empty string would satisfy `str | None` while naming no document
        # at all, which reads downstream as "there was a cover letter" and
        # resolves to nothing.
        if self.cover_letter_document_id is not None and (
            not self.cover_letter_document_id
        ):
            raise InvalidValueError(
                "TrackedApplication.cover_letter_document_id cannot be blank — "
                "use None when no cover letter was sent."
            )
        if not isinstance(self.status, ApplicationStatus):
            raise InvalidValueError(
                "TrackedApplication requires a valid ApplicationStatus."
            )
        # DRAFT belongs to `ApplicationReview`, not here. Allowing it would
        # make `applied_at` a date on which nothing happened.
        if self.status is ApplicationStatus.DRAFT:
            raise InvalidValueError(
                "A tracked application cannot be in "
                f"'{ApplicationStatus.DRAFT.value}' — this record exists "
                "because the application was sent. An application still being "
                "prepared is an ApplicationReview."
            )
        if self.applied_at.tzinfo is None:
            raise InvalidValueError(
                "TrackedApplication.applied_at must be timezone-aware so "
                "applications order correctly across regions."
            )

    # ---- Construction --------------------------------------------------------

    @classmethod
    def record_sent(
        cls,
        *,
        application_id: str,
        user_id: str,
        job_posting: JobPosting,
        resume_document: ApplicationDocument,
        cover_letter_document: ApplicationDocument | None = None,
        applied_at: datetime | None = None,
    ) -> TrackedApplication:
        """Record that this application was sent, with these exact documents.

        Takes the snapshot entities rather than their ids so the references
        can be *checked*: each has to be the right kind of document and belong
        to this candidate and this posting. A foreign key cannot see any of
        that — `application_documents.id` resolves just as well to another
        job's resume — and an application filed against the wrong document is
        a record that misstates what an employer received.

        Role and company are copied from `job_posting` here, so the tracked
        row cannot disagree with the posting it was created from.
        """
        cls._ensure_document_belongs(
            document=resume_document,
            user_id=user_id,
            job_posting_id=job_posting.id,
            expected_kind_check=lambda document: document.is_tailored_resume,
            expected_kind="tailored resume",
        )
        if cover_letter_document is not None:
            cls._ensure_document_belongs(
                document=cover_letter_document,
                user_id=user_id,
                job_posting_id=job_posting.id,
                expected_kind_check=lambda document: document.is_cover_letter,
                expected_kind="cover letter",
            )
        return cls(
            id=application_id,
            user_id=user_id,
            job_posting_id=job_posting.id,
            company_name=job_posting.company,
            role_title=job_posting.title,
            applied_at=applied_at if applied_at is not None else _utcnow(),
            resume_document_id=resume_document.id,
            cover_letter_document_id=(
                cover_letter_document.id if cover_letter_document is not None else None
            ),
            status=ApplicationStatus.APPLIED,
        )

    # ---- Behaviors (business rules live here) --------------------------------

    def change_status(self, target: ApplicationStatus) -> None:
        """Move the application to a new status, enforcing valid transitions.

        The transition rules are `ApplicationStatus`'s own — reused rather
        than restated, so the tracker and the rest of the system cannot come
        to different conclusions about whether a rejected application can go
        back to interviewing.
        """
        self.status = self.status.transition_to(target)
        self._touch()

    def attach_cover_letter(self, document: ApplicationDocument) -> None:
        """Record that this application also went out with `document`.

        For the case where the letter was archived after the row was created.
        It does not *replace* a letter already referenced: that reference
        states what the employer received, and a tracker that could quietly
        repoint it would be able to rewrite what was sent.
        """
        if self.cover_letter_document_id is not None:
            raise InvalidValueError(
                f"Tracked application '{self.id}' already references the cover "
                "letter that was sent; a sent document cannot be swapped for "
                "another one."
            )
        self._ensure_document_belongs(
            document=document,
            user_id=self.user_id,
            job_posting_id=self.job_posting_id,
            expected_kind_check=lambda candidate: candidate.is_cover_letter,
            expected_kind="cover letter",
        )
        self.cover_letter_document_id = document.id
        self._touch()

    @property
    def is_open(self) -> bool:
        """Whether this application is still live — i.e. not in a terminal
        status. What the tracker's "active applications" view reads."""
        return not self.status.is_terminal

    # ---- Internals -----------------------------------------------------------

    @staticmethod
    def _ensure_document_belongs(
        *,
        document: ApplicationDocument,
        user_id: str,
        job_posting_id: str,
        expected_kind_check: Callable[[ApplicationDocument], bool],
        expected_kind: str,
    ) -> None:
        """Raise unless `document` is the right kind and belongs to this
        candidate and posting."""
        if not expected_kind_check(document):
            raise InvalidValueError(
                f"Application document '{document.id}' is a "
                f"'{document.document_kind.value}', not a {expected_kind}; a "
                "tracked application must reference the document that was "
                "actually sent in that role."
            )
        if document.user_id != user_id:
            raise InvalidValueError(
                f"Application document '{document.id}' belongs to another "
                "candidate and cannot be recorded as this candidate's "
                f"{expected_kind}."
            )
        if document.job_posting_id != job_posting_id:
            raise InvalidValueError(
                f"Application document '{document.id}' was produced for job "
                f"posting '{document.job_posting_id}', not "
                f"'{job_posting_id}' — recording it here would misstate which "
                "document this employer received."
            )

    def _touch(self) -> None:
        self.updated_at = _utcnow()
