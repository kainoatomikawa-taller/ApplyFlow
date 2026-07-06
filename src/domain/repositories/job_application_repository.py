"""JobApplicationRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. The domain and application layers depend only
on this abstraction, never on a specific database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.job_application import JobApplication


class JobApplicationRepository(ABC):
    """Persistence contract for JobApplication aggregates."""

    @abstractmethod
    async def add(self, application: JobApplication) -> None:
        """Persist a new job application."""

    @abstractmethod
    async def get_by_id(self, application_id: str) -> JobApplication | None:
        """Return an application by id, or None if it does not exist."""

    @abstractmethod
    async def update(self, application: JobApplication) -> None:
        """Persist changes to an existing application."""

    @abstractmethod
    async def list_by_candidate(self, candidate_email: str) -> list[JobApplication]:
        """Return all applications belonging to a candidate."""

    @abstractmethod
    async def delete(self, application_id: str) -> None:
        """Remove an application by id."""
