"""DTOs — input/output contracts for the application tracker: reading what a
candidate has sent, and moving one through its lifecycle.

Status arrives as a string and leaves as a string
------------------------------------------------
`UpdateApplicationStatusInput.status` is a plain `str` because that is what
comes off an HTTP request, and the interface layer's job ends at shape. Which
strings are statuses, and which moves between them are allowed, are domain
questions — the use case resolves the string against `ApplicationStatus` and the
entity refuses an illegal transition. A DTO typed to the enum would push that
parsing into the controller, which is where a second, divergent idea of the
lifecycle would eventually grow.

The history travels with the application
---------------------------------------
`TrackedApplicationOutput.status_history` is the whole history, not a count and
not just the latest entry, and the list endpoints carry it too. It is small
(bounded by how many times one application can legitimately move — five, given
the transition rules) and it is the reason the tracker exists: a follow-up view
showing "applied 21 days ago, no reply" needs `current_status_since`, and an
interview-prep view needs to know a screen already happened. Fetching that
per-row afterwards would be a request per application.

`current_status_since` is derived in the mapper rather than recomputed by every
caller — it is the last entry's timestamp, and a client that re-derived it from
the history would eventually disagree about which entry is last.

The documents are carried twice, by id and resolved
---------------------------------------------------
`resume_document_id` / `cover_letter_document_id` are always present: they are
on the row, they cost nothing, and they are what a caller needs to fetch a
document. `resume` / `cover_letter` are the *resolved* snapshots
(`SentDocumentOutput`), populated by the reads that follow those references so
a tracker screen can name what went out — version and digest — without a
round trip per row.

Resolved deliberately **by id**, never by "the newest document for this job".
`get_latest` is the right question at send time and the wrong one afterwards: a
candidate who revises their resume has a newer version stored against the same
job, and reading it would show a document the employer never received. That is
the failure the whole snapshot-by-id design exists to prevent.

They carry no document text. `ApplicationDocumentSummaryOutput` draws the same
line for the same reason — a list view never displays a resume, the text is the
most PII-dense content in the system, and a caller that wants it asks for one
document by id. `content_sha256` is what keeps the reference checkable without
shipping the content.

`resume` is optional even though `resume_document_id` is required. Not a
weakening of the rule: it is None when the caller did not resolve the
references, or when the reference no longer resolves — which the repository
already refuses to create (`TrackedApplicationReferenceError`). Reporting the
row with an empty reference beats hiding a sent application because one join
came back empty.

`allowed_next_statuses` is `ApplicationStatus.allowed_transitions`, passed
straight through, so the choices a client offers and the transitions the domain
accepts come from one place. A status control that computed its own options
would eventually offer one `change_status` refuses.

Not sensitive, with one caveat: `ApplicationStatusChangeOutput.note` is free
text the candidate wrote. Safe to return to its owner, not something to log —
see `ApplicationStatusChange.note`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class UpdateApplicationStatusInput:
    """Move one tracked application to a new status.

    `user_id` is not decoration: it scopes the lookup, so an id belonging to
    another candidate resolves to "not found" rather than to their application.
    """

    user_id: str
    application_id: str
    status: str
    #: The candidate's own note about this change. Optional — empty means they
    #: did not say why, which is not the same as a note saying nothing.
    note: str = ""


@dataclass(frozen=True)
class GetTrackedApplicationInput:
    user_id: str
    application_id: str


@dataclass(frozen=True)
class ListTrackedApplicationsInput:
    """List a candidate's sent applications, most recently applied first.

    `statuses` is the filter behind the tracker's views. None means every
    status. `open_only` is the one convenience on top of it: "what is still
    live" is the most common view and the set of live statuses is a domain
    rule, so the use case resolves it from `ApplicationStatus.is_terminal`
    rather than making every caller list the statuses it thinks are open.

    Setting both is a contradiction rather than an intersection, and the use
    case refuses it — a caller that asked for "open applications, specifically
    the rejected ones" has a bug, and silently returning nothing would hide it.
    """

    user_id: str
    statuses: tuple[str, ...] | None = None
    open_only: bool = False
    limit: int = 100


@dataclass(frozen=True)
class ListApplicationsForJobInput:
    """Every application this candidate sent to one posting — normally one, but
    re-applying after six months is two real applications."""

    user_id: str
    job_posting_id: str


@dataclass(frozen=True)
class SentDocumentOutput:
    """One document as it went out with an application.

    No `content`: see the module docstring. `content_sha256` identifies the
    exact bytes without carrying them, which is what makes "this is the
    document the employer received" a checkable claim rather than a label.
    """

    id: str
    document_kind: str
    version: int
    content_sha256: str
    created_at: datetime


@dataclass(frozen=True)
class ApplicationStatusChangeOutput:
    """One entry in an application's status history.

    `previous_status` is None for exactly one entry: the first, recorded when
    the application was sent.
    """

    status: str
    changed_at: datetime
    previous_status: str | None = None
    note: str = ""


@dataclass(frozen=True)
class TrackedApplicationOutput:
    """One sent application, where it stands, and how it got there."""

    id: str
    job_posting_id: str
    company_name: str
    role_title: str
    applied_at: datetime
    status: str
    #: Whether the application is still live — i.e. not in a terminal status.
    #: Derived from the domain's own rule so a client cannot reach a different
    #: conclusion about what "open" means.
    is_open: bool
    #: When it entered the status it is in now. Equals `applied_at` until the
    #: application first moves. The field a follow-up view sorts on.
    current_status_since: datetime
    resume_document_id: str
    cover_letter_document_id: str | None = None
    #: The posting's location, snapshotted at record time — the third
    #: component of the identity the matching layer suppresses against.
    job_location: str | None = None
    #: Where this application may go next, from `ApplicationStatus`. Empty in a
    #: terminal status, which is how a client knows to render the status as
    #: settled rather than as an editable control.
    allowed_next_statuses: list[str] = field(default_factory=list)
    #: The archived resume that went out, resolved from `resume_document_id`.
    #: See the module docstring for when this is None.
    resume: SentDocumentOutput | None = None
    #: The archived cover letter, when the application went out with one.
    cover_letter: SentDocumentOutput | None = None
    status_history: list[ApplicationStatusChangeOutput] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
