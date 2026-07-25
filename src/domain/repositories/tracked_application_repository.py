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
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.tracked_application import TrackedApplication


class TrackedApplicationRepository(ABC):
    """Persistence contract for tracked applications."""

    @abstractmethod
    async def add(self, application: TrackedApplication) -> None:
        """Persist a newly recorded application."""

    @abstractmethod
    async def get_by_id(self, application_id: str) -> TrackedApplication | None:
        """Return one tracked application by id, or None if it does not exist."""

    @abstractmethod
    async def update(self, application: TrackedApplication) -> None:
        """Persist a change to an existing tracked application — in practice a
        status transition (see `TrackedApplication.change_status`)."""

    @abstractmethod
    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[TrackedApplication]:
        """Return a candidate's applications across every job, most recently
        applied first. The tracker's main feed."""

    @abstractmethod
    async def list_for_job(
        self, *, user_id: str, job_posting_id: str
    ) -> list[TrackedApplication]:
        """Return every application this candidate has made to one posting,
        most recently applied first — normally one, but see the module
        docstring on re-applying."""
