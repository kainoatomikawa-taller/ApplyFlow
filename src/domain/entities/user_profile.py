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
from src.domain.value_objects.address import Address
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.work_authorization import WorkAuthorization


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
    address: Address = field(default_factory=Address)
    links: ProfileLinks = field(default_factory=ProfileLinks)
    # Sensitive — see WorkAuthorization/EeoSelfIdentification docstrings.
    # Both default to None: an application's "always-asked" fields are only
    # ever populated by an explicit candidate action, never assumed.
    work_authorization: WorkAuthorization | None = None
    eeo_self_identification: EeoSelfIdentification | None = None
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

    def set_address(self, address: Address) -> None:
        self.address = address
        self._touch()

    def set_links(self, links: ProfileLinks) -> None:
        self.links = links
        self._touch()

    def set_work_authorization(
        self, work_authorization: WorkAuthorization | None
    ) -> None:
        """Set or clear work-authorization data.

        Accepting `None` lets a candidate withdraw previously-provided data;
        nothing here ever fills in a value on the candidate's behalf.
        """
        self.work_authorization = work_authorization
        self._touch()

    def set_eeo_self_identification(
        self, eeo_self_identification: EeoSelfIdentification | None
    ) -> None:
        """Set or clear voluntary EEO self-identification data.

        Accepting `None` lets a candidate withdraw previously-provided data;
        nothing here ever fills in a value on the candidate's behalf.
        """
        self.eeo_self_identification = eeo_self_identification
        self._touch()

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
