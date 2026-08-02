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
    status_history: list[ApplicationStatusChangeOutput] = field(default_factory=list)
    updated_at: datetime | None = None
