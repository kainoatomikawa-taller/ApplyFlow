"""ProfileRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. The domain and application layers depend only
on this abstraction, never on a specific database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.user_profile import UserProfile


class ProfileRepository(ABC):
    """Persistence contract for UserProfile aggregates."""

    @abstractmethod
    async def add(self, profile: UserProfile) -> None:
        """Persist a new profile, along with its work/education/skill entries."""

    @abstractmethod
    async def get_by_id(self, profile_id: str) -> UserProfile | None:
        """Return a profile by id, or None if it does not exist."""

    @abstractmethod
    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        """Return the profile belonging to the given user, or None."""

    @abstractmethod
    async def update(self, profile: UserProfile) -> None:
        """Persist changes to an existing profile, syncing child entries."""

    @abstractmethod
    async def delete(self, profile_id: str) -> None:
        """Remove a profile and all of its work/education/skill entries."""
