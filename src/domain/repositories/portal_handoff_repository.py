"""PortalHandoffRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation lives in
infrastructure/. The domain and application layers depend only on this
abstraction, never on a specific database.

Why a hand-off is stored at all
-------------------------------
Because a pause that only exists in memory is not a hand-off. The candidate is
told to go and do something in another browser tab, which means the state has
to survive the request that created it, a page reload, a worker restart, and a
day of not getting around to it. That is what makes it resumable rather than
merely reported.

Why `update` exists here and not on the document store
------------------------------------------------------
`ApplicationDocumentRepository` deliberately has no `update`, because a
snapshot of what was sent must not be rewritable. A hand-off is the opposite
kind of record: it is *supposed* to change, from awaiting to resolved, and the
transition is guarded by `HandoffStatus` in the domain rather than by the
absence of a method here. What it must never do is silently split into two
rows for the same unresolved portal, which is why `get_open_for_job` exists —
a writer checks for the open one and refreshes it (`PortalHandoff.redetected`)
instead of adding another.

`list_for_user` returns resolved hand-offs too, and that is not an oversight:
"this portal needed me to sign in and I dealt with it yesterday" is exactly
the context that stops a candidate re-doing the step, so the panel showing
hand-offs shows recent history, not only the open ones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.portal_handoff import PortalHandoff


class PortalHandoffRepository(ABC):
    """Persistence contract for hand-offs to the candidate."""

    @abstractmethod
    async def add(self, handoff: PortalHandoff) -> None:
        """Persist a newly opened hand-off."""

    @abstractmethod
    async def update(self, handoff: PortalHandoff) -> None:
        """Persist a changed hand-off — a refreshed detection, or a
        resolution. Raises `PortalHandoffNotFoundError` if it does not exist,
        since
        an update that silently inserts would resurrect a hand-off the
        candidate already cleared."""

    @abstractmethod
    async def get_by_id(self, handoff_id: str) -> PortalHandoff | None:
        """Return one hand-off by id, or None if it does not exist."""

    @abstractmethod
    async def get_open_for_job(
        self, *, user_id: str, job_posting_id: str
    ) -> PortalHandoff | None:
        """Return the hand-off still awaiting this candidate on this posting,
        or None.

        At most one can exist — enforced in the database as well, since two
        concurrent inspections of the same portal would otherwise each open
        one and the candidate would be asked to do the same thing twice.
        """

    @abstractmethod
    async def list_for_user(
        self, user_id: str, *, limit: int = 100
    ) -> list[PortalHandoff]:
        """Return this candidate's hand-offs, open and resolved, newest
        first."""
