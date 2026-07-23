"""WorkHistoryEntry entity — one employment period on a candidate's profile.

Owned by the `UserProfile` aggregate; it has no lifecycle of its own outside
of a profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.domain.exceptions import InvalidValueError


@dataclass
class WorkHistoryEntry:
    """A single job held by the candidate."""

    id: str
    company_name: str
    job_title: str
    start_date: date
    end_date: date | None = None
    location: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("WorkHistoryEntry requires a non-empty id.")
        if not self.company_name.strip():
            raise InvalidValueError("company_name cannot be empty.")
        if not self.job_title.strip():
            raise InvalidValueError("job_title cannot be empty.")
        if self.end_date is not None and self.end_date < self.start_date:
            raise InvalidValueError("end_date cannot be before start_date.")

    @property
    def is_current(self) -> bool:
        return self.end_date is None
