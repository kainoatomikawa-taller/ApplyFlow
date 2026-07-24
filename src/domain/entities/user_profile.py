"""UserProfile entity — the aggregate root of the ApplyFlow profile domain.

Everything ApplyFlow knows about a candidate — contact details, work
history, education, and skills — hangs off this aggregate. It is the data
spine that matching, tailoring, and autofill all read from.

Provenance: every fact here is tagged with a `ProvenanceSource` (see that
module for the full downstream contract). List-shaped facts
(`WorkHistoryEntry`, `EducationEntry`, `Skill`) and the facts that live in
their own DB row (`WorkAuthorization`, `EeoSelfIdentification`) each carry
their own `source`. The scalar contact fields (`full_name`, `email`,
`phone`, `headline`, `location`) and the `address`/`links` value objects
are flattened onto this single row rather than given their own table, so
each of those groups shares one `*_source` tag here instead — `contact_source`
(always required, since `full_name`/`email` are always present) and the
optional `address_source`/`links_source` (required only once their group
actually carries data; see `_validate_optional_source`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import BusinessRuleViolationError, InvalidValueError
from src.domain.value_objects.address import Address
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
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
    # Provenance for full_name/email/phone/headline/location as a bundle —
    # see the module docstring's "Provenance" section for why these five
    # scalars share one tag instead of one each.
    contact_source: ProvenanceSource
    phone: str | None = None
    headline: str | None = None
    location: str | None = None
    address: Address = field(default_factory=Address)
    address_source: ProvenanceSource | None = None
    links: ProfileLinks = field(default_factory=ProfileLinks)
    links_source: ProvenanceSource | None = None
    # Sensitive — see WorkAuthorization/EeoSelfIdentification docstrings.
    # Both default to None: an application's "always-asked" fields are only
    # ever populated by an explicit candidate action, never assumed. Each
    # carries its own `source` internally (see their docstrings) since each
    # lives in its own DB row, unlike address/links above.
    work_authorization: WorkAuthorization | None = None
    # Candidate-held clearance/degree, compared against a job posting's
    # `JobRequirements.clearance_level`/`degree_level` by
    # `HardDisqualifierFilter` — reusing the same enums the job side
    # extracts into, so no translation layer is needed between the two.
    # Both default to None ("not provided"), never guessed: an unstated
    # value is treated as unknown rather than "candidate has none", so
    # filtering never disqualifies over a gap in the candidate's own data.
    clearance_level: ClearanceLevel | None = None
    highest_degree: DegreeLevel | None = None
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
        if not isinstance(self.contact_source, ProvenanceSource):
            raise InvalidValueError(
                "UserProfile requires a valid ProvenanceSource for contact_source."
            )
        self._validate_optional_source(
            has_data=self.address != Address(),
            source=self.address_source,
            field_label="address_source",
        )
        self._validate_optional_source(
            has_data=self.links != ProfileLinks(),
            source=self.links_source,
            field_label="links_source",
        )

    @staticmethod
    def _validate_optional_source(
        *, has_data: bool, source: ProvenanceSource | None, field_label: str
    ) -> None:
        """A group of optional fields needs a source once any of them is
        set — but an all-empty group (nothing provided) is not a fact yet,
        so it doesn't need one."""
        if has_data and source is None:
            raise InvalidValueError(f"{field_label} is required once data is set.")
        if source is not None and not isinstance(source, ProvenanceSource):
            raise InvalidValueError(f"{field_label} must be a valid ProvenanceSource.")

    # ---- Behaviors (business rules live here) --------------------------------

    def set_address(
        self, address: Address, source: ProvenanceSource | None = None
    ) -> None:
        """Set or clear the candidate's address.

        `source` is required whenever `address` carries any data — see
        `_validate_optional_source`. Clearing back to an empty `Address()`
        needs no source, since there is no fact left to attribute.
        """
        self._validate_optional_source(
            has_data=address != Address(), source=source, field_label="source"
        )
        self.address = address
        self.address_source = source
        self._touch()

    def set_links(
        self, links: ProfileLinks, source: ProvenanceSource | None = None
    ) -> None:
        """Set or clear the candidate's links. Same source rule as `set_address`."""
        self._validate_optional_source(
            has_data=links != ProfileLinks(), source=source, field_label="source"
        )
        self.links = links
        self.links_source = source
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

    def set_clearance_level(self, clearance_level: ClearanceLevel | None) -> None:
        """Set or clear the candidate's held security clearance."""
        self.clearance_level = clearance_level
        self._touch()

    def set_highest_degree(self, highest_degree: DegreeLevel | None) -> None:
        """Set or clear the candidate's highest completed degree level."""
        self.highest_degree = highest_degree
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
