"""JobApplication entity — the aggregate root of the ApplyFlow domain.

An entity has identity and a lifecycle. It protects its own invariants:
validation lives inside the constructor and the behavior methods, never
in controllers or use cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.application_status import ApplicationStatus
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.match_score import MatchScore


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class JobApplication:
    """Represents a single candidate's application to a single job."""

    id: str
    candidate_email: EmailAddress
    company_name: str
    role_title: str
    job_description: str
    status: ApplicationStatus = ApplicationStatus.DRAFT
    match_score: MatchScore | None = None
    tailored_cover_letter: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("JobApplication requires a non-empty id.")
        if not self.company_name.strip():
            raise InvalidValueError("company_name cannot be empty.")
        if not self.role_title.strip():
            raise InvalidValueError("role_title cannot be empty.")
        if not self.job_description.strip():
            raise InvalidValueError("job_description cannot be empty.")

    # ---- Behaviors (business rules live here) --------------------------------

    def change_status(self, target: ApplicationStatus) -> None:
        """Move the application to a new status, enforcing valid transitions."""
        self.status = self.status.transition_to(target)
        self._touch()

    def attach_analysis(
        self, score: MatchScore, cover_letter: str | None = None
    ) -> None:
        """Attach the result of an AI analysis to the application."""
        self.match_score = score
        if cover_letter is not None:
            if not cover_letter.strip():
                raise InvalidValueError("cover_letter cannot be blank when provided.")
            self.tailored_cover_letter = cover_letter
        self._touch()

    def submit(self) -> None:
        """Submit the application (DRAFT -> APPLIED)."""
        self.change_status(ApplicationStatus.APPLIED)

    def _touch(self) -> None:
        self.updated_at = _utcnow()
