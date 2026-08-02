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

Why role, company, and location are stored, not read through the posting
------------------------------------------------------------------------
They are copied from `JobPosting` at record time. A posting is a live row —
re-ingested, re-normalized, retitled by the employer, eventually marked
stale — while this row states what the candidate applied to *then*. Deriving
the label on every read would let a posting edited in June rewrite the history
of an application sent in March. `record_sent` copies them from the posting so
the two cannot disagree at the moment it matters.

Those three fields are also what `canonical_identity` is built from, and that
is the second reason they are snapshotted rather than joined: the matching
layer suppresses roles the candidate has already applied to (see
`AppliedJobIndex`), and it has to keep suppressing them after the posting they
were applied through is pruned, relisted under a new id, or picked up again
from a different aggregator. A join would lose the answer in exactly the cases
the suppression exists for.

Why the status history is part of this aggregate
-----------------------------------------------
`status` and `status_history` are two views of one fact, so they are loaded,
validated, and saved together. The alternative — a separate history table with
its own repository — would let the two be written independently, and the first
partial failure would leave an application whose current status is `offer` and
whose history ends at `applied`. Which of those a reader trusted would then
depend on which query it ran.

Keeping them together means the invariant can simply be enforced:
`status_history[-1].status` *is* `status`, checked on construction (see
`_validate_history`). `change_status` is the only way to move an application,
and it appends and reassigns in one step, so the two cannot drift apart.

The history is append-only. There is no operation here that edits or removes an
entry, because a status change is something that happened — and a tracker whose
history could be rewritten would be no better evidence of a search than memory.

Not sensitive. A role title, a company name, and a status carry nothing that
`WorkAuthorization` or `AnswerMemory` do; the sensitive material lives in the
documents this row references, behind their own flags. So this entity is safe
to log — and logging it is the reason its document fields are ids. The one
exception is the free-text note on a status change; see
`ApplicationStatusChange.note`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.application_status_change import ApplicationStatusChange
from src.domain.value_objects.canonical_job_identity import CanonicalJobIdentity


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class TrackedApplication:
    """One application the candidate sent, tracked through its lifecycle."""

    id: str
    user_id: str
    #: The source job record this application was made against.
    job_posting_id: str
    #: Identifies the submission event that produced this row, so logging the
    #: same submission twice cannot produce two records. Supplied by the
    #: caller (the submission flow) rather than generated here — a value this
    #: entity invented would be unique on every attempt, which is the opposite
    #: of an idempotency key. Unique per candidate at the schema level, so a
    #: double-clicked submit button collides in the database rather than
    #: relying on a read that two concurrent requests can both pass.
    submission_key: str
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
    #: The posting's location, copied at record time — the third component of
    #: `canonical_identity`. Optional because plenty of postings name no
    #: location, and `CanonicalJobIdentity` treats "no location" as its own
    #: value rather than as a wildcard. Rows written before this field
    #: existed read back as None, which makes them match only postings that
    #: also name no location — a stale record under-suppresses (the candidate
    #: sees a job again) instead of hiding one they never applied to.
    job_location: str | None = None
    #: The archived cover letter, when the posting asked for one. Optional
    #: because plenty of forms do not, and a fabricated reference would be
    #: worse than an honest absence.
    cover_letter_document_id: str | None = None
    status: ApplicationStatus = ApplicationStatus.APPLIED
    #: Every status this application has held, oldest first, ending at the one
    #: it holds now. Append-only, and never empty once constructed: an empty
    #: history is seeded with the entry for `status` at `applied_at`, which is
    #: what lets a row written before the tracker recorded history still be
    #: read as the one-entry history it truthfully is.
    status_history: list[ApplicationStatusChange] = field(default_factory=list)
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
        if not self.submission_key.strip():
            raise InvalidValueError(
                "TrackedApplication requires a non-empty submission_key — it is "
                "what makes logging the same submission twice a no-op instead "
                "of a duplicate application."
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
        self._validate_history()

    # ---- History -------------------------------------------------------------

    def _validate_history(self) -> None:
        """Seed an empty history, and refuse one that contradicts `status`.

        Seeding is what makes rows that predate status-history tracking
        readable: such a row knows its status and when it was sent, which is
        exactly a one-entry history, so it is loaded as one rather than as an
        application that has never been anywhere.
        """
        if not self.status_history:
            self.status_history = [
                ApplicationStatusChange(
                    status=self.status,
                    changed_at=self.applied_at,
                    previous_status=None,
                )
            ]
            return

        if not all(
            isinstance(entry, ApplicationStatusChange) for entry in self.status_history
        ):
            raise InvalidValueError(
                "TrackedApplication.status_history must contain only "
                "ApplicationStatusChange values."
            )
        # Only the first entry may have nothing before it, and it must.
        # Otherwise the history has either two beginnings or none, and in both
        # cases "what did this application do first?" has no answer.
        if not self.status_history[0].is_initial:
            raise InvalidValueError(
                "TrackedApplication.status_history must begin with the entry "
                "recorded when the application was sent, which has no previous "
                "status."
            )
        for earlier, later in zip(
            self.status_history, self.status_history[1:], strict=False
        ):
            if later.is_initial:
                raise InvalidValueError(
                    "TrackedApplication.status_history can only have one "
                    "initial entry — every later change records what it moved "
                    "from."
                )
            if later.previous_status is not earlier.status:
                raise InvalidValueError(
                    f"TrackedApplication.status_history is inconsistent: an "
                    f"entry moving from '{later.previous_status}' follows one "
                    f"that left the application at '{earlier.status.value}'."
                )
            if later.changed_at < earlier.changed_at:
                raise InvalidValueError(
                    "TrackedApplication.status_history must run oldest first — "
                    "an application cannot change status before the change "
                    "that preceded it."
                )
        # The invariant the whole aggregate exists to keep: the current status
        # is the one the history ends at. A row where these disagree is one
        # that two different queries would answer differently.
        if self.status_history[-1].status is not self.status:
            raise InvalidValueError(
                f"TrackedApplication.status is '{self.status.value}' but its "
                f"history ends at "
                f"'{self.status_history[-1].status.value}' — a tracked "
                "application's status is the one its history arrived at."
            )

    # ---- Construction --------------------------------------------------------

    @classmethod
    def record_sent(
        cls,
        *,
        application_id: str,
        user_id: str,
        job_posting: JobPosting,
        submission_key: str,
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
            submission_key=submission_key,
            company_name=job_posting.company,
            role_title=job_posting.title,
            job_location=job_posting.location,
            applied_at=applied_at if applied_at is not None else _utcnow(),
            resume_document_id=resume_document.id,
            cover_letter_document_id=(
                cover_letter_document.id if cover_letter_document is not None else None
            ),
            status=ApplicationStatus.APPLIED,
        )

    # ---- Behaviors (business rules live here) --------------------------------

    @property
    def canonical_identity(self) -> CanonicalJobIdentity:
        """The role this application was for, as an identity comparable
        against any posting's — see `CanonicalJobIdentity`.

        Built from the snapshotted company/title/location rather than the
        posting, so it keeps answering "already applied to this role" once
        that posting is gone, relisted, or re-ingested from another source.
        """
        return CanonicalJobIdentity.of(
            company=self.company_name,
            title=self.role_title,
            location=self.job_location,
        )

    def change_status(
        self,
        target: ApplicationStatus,
        *,
        note: str = "",
        changed_at: datetime | None = None,
    ) -> ApplicationStatusChange:
        """Move the application to a new status and record the move.

        The transition rules are `ApplicationStatus`'s own — reused rather
        than restated, so the tracker and the rest of the system cannot come
        to different conclusions about whether a rejected application can go
        back to interviewing. A refused transition raises before anything is
        recorded, so a rejected move leaves no trace in the history.

        Appending and reassigning happen together, and that is the point: it
        is not possible to move this application without recording that it
        moved. Returns the entry it recorded, so a caller that wants to report
        or log the transition does not have to re-read the history to find it.

        `changed_at` exists for backfills and for callers that already observed
        the time; it defaults to now. It cannot predate the change before it —
        the history has to stay ordered, so an out-of-order backfill is
        refused rather than quietly sorted into place.
        """
        # `transition_to` raises on an invalid move, including a move to the
        # status it already holds.
        next_status = self.status.transition_to(target)
        occurred_at = changed_at if changed_at is not None else _utcnow()
        entry = ApplicationStatusChange(
            status=next_status,
            changed_at=occurred_at,
            previous_status=self.status,
            note=note,
        )
        if occurred_at < self.status_history[-1].changed_at:
            raise InvalidValueError(
                "A status change cannot be recorded earlier than the change "
                "before it — this application's history already reaches "
                f"{self.status_history[-1].changed_at.isoformat()}."
            )
        self.status_history.append(entry)
        self.status = next_status
        self._touch()
        return entry

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

    @property
    def current_status_since(self) -> datetime:
        """When the application entered the status it is in now.

        The field a follow-up view sorts on: "applied three weeks ago, still
        `applied`" is the case worth surfacing, and `applied_at` cannot express
        it once an application has moved at all.
        """
        return self.status_history[-1].changed_at

    @property
    def last_status_change(self) -> ApplicationStatusChange:
        """The most recent entry in the history. Never None — a constructed
        application always has at least the entry for being sent."""
        return self.status_history[-1]

    def has_held_status(self, status: ApplicationStatus) -> bool:
        """Whether this application was ever in `status`.

        Reads the history rather than the current status, which is the only way
        to answer questions like "how many of my applications reached an
        interview?" — an application rejected after two rounds is `rejected`
        now, and counting it as never having interviewed would understate
        every funnel it appears in.
        """
        return any(entry.status is status for entry in self.status_history)

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
