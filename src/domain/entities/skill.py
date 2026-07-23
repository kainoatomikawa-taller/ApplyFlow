"""Skill entity — one skill claimed on a candidate's profile.

Owned by the `UserProfile` aggregate; it has no lifecycle of its own outside
of a profile.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.proficiency_level import ProficiencyLevel


@dataclass
class Skill:
    """A single skill, optionally rated by proficiency and experience."""

    id: str
    name: str
    proficiency: ProficiencyLevel | None = None
    years_of_experience: int | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("Skill requires a non-empty id.")
        if not self.name.strip():
            raise InvalidValueError("name cannot be empty.")
        if self.years_of_experience is not None and self.years_of_experience < 0:
            raise InvalidValueError("years_of_experience cannot be negative.")
