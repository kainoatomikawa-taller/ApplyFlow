"""ApplicationDocumentRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. The domain and application layers depend only
on this abstraction, never on a specific database.

Write-once by shape, not by discipline
--------------------------------------
There is no `update` here, and that omission is the contract. A snapshot
records what was actually produced for a job (see `ApplicationDocument`),
so a method that rewrote one would make the store unable to answer the only
question it exists for. Regeneration is `add` with the next version, never
an overwrite: `count_versions` is what the writer reads to number it.

There is no `delete` either. Erasing a candidate's data on request is a real
obligation, but it is a deliberate, user-scoped purge (Epic 07's
encryption/retention work), not a general-purpose row deletion that any
caller could reach for — so it belongs in that epic's explicit capability
rather than sitting here as an ambient one.

Downstream contract (Epic 06 — the tracker) and interview prep
--------------------------------------------------------------
Both read through this interface, and both join on (`user_id`,
`job_posting_id`) — the same pair the generation flows write. That is why
the store is keyed on the posting rather than on a tracker row: the posting
id exists at generation time, is stable, and is what the tracker itself
keys its applications by, so neither side has to backfill a link.

- `get_latest` answers "the resume/letter this application went out with",
  which is the reuse path that replaces regenerating one.
- `list_for_job` answers "everything produced for this job, newest first",
  including superseded versions.
- `list_by_user_id` is the tracker's feed across every application.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.application_document import ApplicationDocument
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind


class ApplicationDocumentRepository(ABC):
    """Persistence contract for immutable sent-document snapshots."""

    @abstractmethod
    async def add(self, document: ApplicationDocument) -> None:
        """Persist a new snapshot. Snapshots are write-once — this never
        updates an existing record (see module docstring)."""

    @abstractmethod
    async def get_by_id(self, document_id: str) -> ApplicationDocument | None:
        """Return one snapshot by id, or None if it does not exist."""

    @abstractmethod
    async def count_versions(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
    ) -> int:
        """Return how many snapshots of `document_kind` already exist for
        this user and job posting — what the next version number is counted
        from."""

    @abstractmethod
    async def get_latest(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
    ) -> ApplicationDocument | None:
        """Return the newest stored version of `document_kind` for this user
        and job posting, or None if none was ever produced."""

    @abstractmethod
    async def list_for_job(
        self, *, user_id: str, job_posting_id: str, limit: int = 100
    ) -> list[ApplicationDocument]:
        """Return every snapshot stored for one job posting — both kinds,
        every version — newest first."""

    @abstractmethod
    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[ApplicationDocument]:
        """Return a candidate's snapshots across every job, newest first."""
