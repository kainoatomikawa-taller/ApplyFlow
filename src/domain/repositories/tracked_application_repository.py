"""TrackedApplicationRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation lives in
infrastructure/. The domain and application layers depend only on this
abstraction, never on a specific database.

Mutable, unlike the document store
----------------------------------
`ApplicationDocumentRepository` deliberately has no `update`, because a
snapshot of a sent document is a fact that cannot change. A tracked
application is the opposite: its whole purpose is to follow an application
*through* its lifecycle, so `update` is how a rejection or an interview
invitation gets recorded. What cannot change is which documents it points at —
that invariant is enforced by `TrackedApplication`, not by omitting a method
here.

No `delete`, for the same reason the document store has none: erasing a
candidate's data is a deliberate, user-scoped purge (Epic 07's
retention work), not an ambient capability every caller can reach for.

Keyed by (`user_id`, `job_posting_id`), like everything else downstream of
ingestion — the pair the document store is also keyed on, so the tracker can
join an application to the documents it was sent with and to the posting it
came from without a backfilled link anywhere.

Applying to the same posting twice is two rows, not one. There is no
uniqueness constraint on that pair and there should not be: a candidate who
applies again after six months has made two applications, each with its own
date, its own documents, and its own outcome. `list_for_job` returns them.

Status is filtered in the query, not by the caller
-------------------------------------------------
`list_by_user_id` takes a `statuses` filter because "show me what is still
live" and "show me everything" are different questions, and answering the
first by fetching every application and discarding most of them gets slower
exactly as a candidate's search gets longer. The database has an index on
(`user_id`, `status`) for this.

The filter names statuses explicitly rather than offering an `open_only` flag.
Which statuses count as open is a domain rule (`ApplicationStatus.is_terminal`),
and a boolean here would be a second copy of it — one that could disagree the
moment a status was added.

Every implementation returns whole aggregates, history included. A
`TrackedApplication` whose `status_history` was left empty because a caller
"only needed the list" would be indistinguishable from one that has never
moved, and the entity would helpfully seed it into a lie.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection

from src.domain.entities.tracked_application import TrackedApplication
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.canonical_job_identity import CanonicalJobIdentity


class TrackedApplicationRepository(ABC):
    """Persistence contract for tracked applications."""

    @abstractmethod
    async def add(self, application: TrackedApplication) -> None:
        """Persist a newly recorded application."""

    @abstractmethod
    async def get_by_id(self, application_id: str) -> TrackedApplication | None:
        """Return one tracked application by id, or None if it does not exist."""

    @abstractmethod
    async def get_by_submission_key(
        self, *, user_id: str, submission_key: str
    ) -> TrackedApplication | None:
        """Return the application already logged for this submission event, or
        None if it has not been logged yet.

        The read half of idempotent logging: a retry, a double-clicked submit
        button, or a repair pass finds the existing row here instead of writing
        a second one. The write half is the unique constraint behind
        `add` — this read alone cannot make logging idempotent, because two
        concurrent callers can both find nothing.
        """

    @abstractmethod
    async def update(self, application: TrackedApplication) -> None:
        """Persist a change to an existing tracked application — in practice a
        status transition (see `TrackedApplication.change_status`).

        Saves the row and any newly appended history entries together, in one
        transaction. That atomicity is the reason the history is part of this
        aggregate rather than a store of its own: a commit that moved the
        status without its history entry would leave a record whose current
        state and past disagree, and no later read could tell which was right.

        The history is append-only, so an implementation appends the entries it
        has not already stored and never rewrites the ones it has.
        """

    @abstractmethod
    async def list_by_user_id(
        self,
        user_id: str,
        *,
        statuses: Collection[ApplicationStatus] | None = None,
        limit: int = 100,
    ) -> list[TrackedApplication]:
        """Return a candidate's applications across every job, most recently
        applied first. The tracker's main feed.

        `statuses` narrows the feed to those statuses — the tracker's filtered
        views ("still live", "offers", "everything I withdrew"). None means no
        filter; an *empty* collection means no status is acceptable and returns
        nothing, because a caller that filtered its own list down to nothing
        asked a different question than one that did not filter at all.
        """

    @abstractmethod
    async def list_for_job(
        self, *, user_id: str, job_posting_id: str
    ) -> list[TrackedApplication]:
        """Return every application this candidate has made to one posting,
        most recently applied first — normally one, but see the module
        docstring on re-applying."""

    @abstractmethod
    async def list_applied_identities(
        self, *, user_id: str
    ) -> list[CanonicalJobIdentity]:
        """Return the distinct roles this candidate has applied to — what the
        matching layer suppresses against (see `AppliedJobIndex`).

        Deliberately not `list_by_user_id`, for two reasons. It must be
        *complete*: a limit would silently un-suppress the oldest
        applications, and "you already applied to this" turning back into a
        nudge after the hundredth application is worse than no suppression at
        all, because it looks like the feature works. And it needs three short
        columns rather than whole records, so completeness costs little even
        for a candidate with years of history.

        Identities come back already normalized through `CanonicalJobIdentity`,
        so no implementation gets to invent its own notion of "the same role".
        Distinct: applying to one role twice is two records but one identity.
        Ordering is unspecified — the caller builds a set from it.
        """
