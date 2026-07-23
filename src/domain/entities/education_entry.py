"""EducationEntry entity — one program of study on a candidate's profile.

Owned by the `UserProfile` aggregate; it has no lifecycle of its own outside
of a profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.domain.exceptions import InvalidValueError


@dataclass
class EducationEntry:
    """A single school/program attended by the candidate."""

    id: str
    institution_name: str
    degree: str
    field_of_study: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("EducationEntry requires a non-empty id.")
        if not self.institution_name.strip():
            raise InvalidValueError("institution_name cannot be empty.")
        if not self.degree.strip():
            raise InvalidValueError("degree cannot be empty.")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise InvalidValueError("end_date cannot be before start_date.")
