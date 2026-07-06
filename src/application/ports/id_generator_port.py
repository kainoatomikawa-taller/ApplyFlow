"""IdGeneratorPort — abstraction for generating unique identifiers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IdGeneratorPort(ABC):
    """Generates unique ids for new aggregates."""

    @abstractmethod
    def new_id(self) -> str:
        """Return a new unique identifier."""
