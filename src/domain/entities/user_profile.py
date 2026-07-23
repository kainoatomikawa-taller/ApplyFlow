"""UserProfile entity — the aggregate root of the ApplyFlow profile domain.

Everything ApplyFlow knows about a candidate — contact details, work
history, education, and skills — hangs off this aggregate. It is the data
spine that matching, tailoring, and autofill all read from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import BusinessRuleViolationError, InvalidValueError
from src.domain.value_objects.email_address import EmailAddress


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class UserProfile:
    """A candidate's profile: contact info plus work/education/skill history."""

    id: str
    user_id: str
    full_name: str
    email: EmailAddress
    phone: str | None = None
    headline: str | None = None
    location: str | None = None
    work_history: list[WorkHistoryEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("UserProfile requires a non-empty id.")
        if not self.user_id:
            raise InvalidValueError("UserProfile requires a non-empty user_id.")
        if not self.full_name.strip():
            raise InvalidValueError("full_name cannot be empty.")

    # ---- Behaviors (business rules live here) --------------------------------

    def add_work_history(self, entry: WorkHistoryEntry) -> None:
        if any(e.id == entry.id for e in self.work_history):
            raise BusinessRuleViolationError(
                f"Work history entry '{entry.id}' already exists on this profile."
            )
        self.work_history.append(entry)
        self._touch()

    def add_education(self, entry: EducationEntry) -> None:
        if any(e.id == entry.id for e in self.education):
            raise BusinessRuleViolationError(
                f"Education entry '{entry.id}' already exists on this profile."
            )
        self.education.append(entry)
        self._touch()

    def add_skill(self, skill: Skill) -> None:
        skill_name = skill.name.strip().lower()
        if any(s.name.strip().lower() == skill_name for s in self.skills):
            raise BusinessRuleViolationError(
                f"Skill '{skill.name}' already exists on this profile."
            )
        self.skills.append(skill)
        self._touch()

    def _touch(self) -> None:
        self.updated_at = _utcnow()
