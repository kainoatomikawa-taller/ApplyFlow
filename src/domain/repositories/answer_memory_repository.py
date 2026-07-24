"""AnswerMemoryRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. The domain and application layers depend only
on this abstraction, never on a specific database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.answer_memory import AnswerMemory


class AnswerMemoryRepository(ABC):
    """Persistence contract for `AnswerMemory` records."""

    @abstractmethod
    async def add(self, answer_memory: AnswerMemory) -> None:
        """Persist a newly remembered question/answer pair."""

    @abstractmethod
    async def get_by_id(self, answer_memory_id: str) -> AnswerMemory | None:
        """Return an answer memory by id, or None if it does not exist."""

    @abstractmethod
    async def list_by_user_id(self, user_id: str) -> list[AnswerMemory]:
        """Return every answer memory a user has, newest first."""

    @abstractmethod
    async def delete(self, answer_memory_id: str) -> None:
        """Remove an answer memory."""
