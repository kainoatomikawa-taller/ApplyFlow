"""ResumeRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. The domain and application layers depend only
on this abstraction, never on a specific database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.resume import Resume


class ResumeRepository(ABC):
    """Persistence contract for `Resume` metadata (not the raw file bytes —
    see `FileStoragePort` in the application layer for those)."""

    @abstractmethod
    async def add(self, resume: Resume) -> None:
        """Persist a newly uploaded resume's metadata."""

    @abstractmethod
    async def get_by_id(self, resume_id: str) -> Resume | None:
        """Return a resume by id, or None if it does not exist."""

    @abstractmethod
    async def list_by_user_id(self, user_id: str) -> list[Resume]:
        """Return every resume a user has uploaded, newest first."""

    @abstractmethod
    async def delete(self, resume_id: str) -> None:
        """Remove a resume's metadata row."""
