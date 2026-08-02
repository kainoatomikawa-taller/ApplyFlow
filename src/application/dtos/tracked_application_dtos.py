"""DTOs — input/output contracts for reading and maintaining the tracker
(Epic 06).

What a tracker row has to be able to answer
-------------------------------------------
Two questions, and they are the two acceptance criteria this epic is graded
on: *what did I send?* and *where does it stand?* So `TrackedApplicationOutput`
carries the role, the company, the date, the status — and `resume` /
`cover_letter`, resolved from the ids on the row into the actual snapshots
that went out.

Resolved, rather than left as ids
---------------------------------
The entity stores `resume_document_id` for good reasons (see
`TrackedApplication`), but a client handed two opaque ids has to make two more
round trips per row before it can show anything, and thirty rows becomes sixty
requests. So the use case follows the references once and the output carries
`SentDocumentOutput` — the id, the kind, the version, and the digest.

Deliberately *without* the document text. `ApplicationDocumentSummaryOutput`
draws the same line for the same reason: the text is the most PII-dense
content in the system, a list view never displays it, and a caller that wants
it asks for one document by id. `content_sha256` is what makes the reference
checkable without shipping the content — a client can prove the document it is
looking at is the one that was archived.

`resume` is optional in the *output* even though it is required on the entity.
Not a weakening of the rule: it is None only when the reference no longer
resolves, which the repository already refuses to create
(`TrackedApplicationReferenceError`). Reporting the row with an empty
reference beats hiding a sent application because one join came back empty.

`allowed_next_statuses` comes from the domain
---------------------------------------------
It is `ApplicationStatus.allowed_transitions`, passed straight through, so the
choices a client offers and the transitions the domain accepts come from one
place. A status control that computed its own options would eventually offer
one `change_status` refuses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ListTrackedApplicationsInput:
    """Read a candidate's tracker feed, most recently applied first."""

    user_id: str
    limit: int = 100


@dataclass(frozen=True)
class UpdateTrackedApplicationStatusInput:
    """Move one logged application to a new status.

    `status` is a plain string at this boundary — the interface layer passes
    through whatever arrived on the request, and the use case is what resolves
    it to an `ApplicationStatus` or rejects it. `user_id` is not decoration:
    it is what scopes the write to the candidate's own row.
    """

    user_id: str
    application_id: str
    status: str


@dataclass(frozen=True)
class SentDocumentOutput:
    """One document as it went out with an application.

    No `content`: see the module docstring. `content_sha256` identifies the
    exact bytes without carrying them.
    """

    id: str
    document_kind: str
    version: int
    content_sha256: str
    created_at: datetime


@dataclass(frozen=True)
class TrackedApplicationOutput:
    """One logged application: what was sent, and where it stands."""

    id: str
    job_posting_id: str
    company_name: str
    role_title: str
    applied_at: datetime
    status: str
    #: False once the application reaches a terminal status. What an "active
    #: applications" filter reads, taken from the domain rather than from a
    #: hardcoded list of which statuses count as finished.
    is_open: bool
    #: Where this application may go next, from `ApplicationStatus`. Empty in
    #: a terminal status, which is how a client knows to render the status as
    #: settled rather than as an editable control.
    allowed_next_statuses: list[str] = field(default_factory=list)
    job_location: str | None = None
    #: The archived resume that went out. None only if the reference no
    #: longer resolves — see the module docstring.
    resume: SentDocumentOutput | None = None
    #: The archived cover letter, when the application went out with one.
    #: Ordinarily absent: plenty of forms never ask.
    cover_letter: SentDocumentOutput | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
