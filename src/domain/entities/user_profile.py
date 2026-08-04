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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    ProfileEntryNotFoundError,
)
from src.domain.value_objects.address import Address
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_search_preferences import JobSearchPreferences
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _HasEntryId(Protocol):
    """What `_index_of` needs of a list entry: an id to match on.

    A structural type rather than a shared base class, so `WorkHistoryEntry`,
    `EducationEntry` and `Skill` stay independent of each other — they have
    nothing else in common and giving them a common ancestor for the sake of one
    private lookup would be inheritance for a helper's convenience.
    """

    @property
    def id(self) -> str: ...


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
    #: The other two names an application form asks for, both optional and both
    #: covered by `contact_source` like the rest of this group.
    #:
    #: Blank means something definite in each case, and the two meanings differ:
    #:
    #: - `middle_name` blank means "I have no middle name". A form asking for one
    #:   gets nothing written into it rather than being handed back — see
    #:   `profile_field_values`, which is where that reading is applied.
    #: - `preferred_name` blank means "the same name I go by legally", so the
    #:   slot falls back to the first name derived from `full_name`.
    #:
    #: Neither is guessed from the other. Storing the absence as a real answer is
    #: what keeps an optional field from becoming a question on every
    #: application.
    middle_name: str | None = None
    preferred_name: str | None = None
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
    # What the candidate is looking for, as opposed to what is true about them.
    # No provenance tag: a preference is never asserted to an employer and can
    # only ever be the candidate's own statement — see `JobSearchPreferences`.
    # Empty means "not stated", so matching narrows nothing.
    job_search_preferences: JobSearchPreferences = field(
        default_factory=JobSearchPreferences
    )
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

    def set_contact_details(
        self,
        *,
        full_name: str,
        email: EmailAddress,
        source: ProvenanceSource,
        phone: str | None = None,
        headline: str | None = None,
        location: str | None = None,
        middle_name: str | None = None,
        preferred_name: str | None = None,
    ) -> None:
        """Replace the contact group in one call.

        A setter rather than direct attribute assignment for the reason every
        other mutator here exists: these seven fields share one
        `contact_source`, and writing one of them without the others' knowledge
        would leave that tag describing a mix of provenances. Assigning the
        attributes directly also skips `_touch()`, so `updated_at` would go
        stale — which it silently did before this method existed, since nothing
        in the codebase could write these fields at all.

        `source` is required, not optional. Unlike address and links, this group
        is never empty — `full_name` and `email` are mandatory on the aggregate —
        so there is no "nothing to attribute" case to allow.

        Keyword-only, because seven mostly-optional strings in a row is exactly
        the signature where a positional call puts a location into a headline.
        """
        if not full_name.strip():
            raise InvalidValueError("full_name cannot be empty.")
        if not isinstance(source, ProvenanceSource):
            raise InvalidValueError(
                "set_contact_details requires a valid ProvenanceSource."
            )
        self.full_name = full_name
        self.email = email
        self.contact_source = source
        self.phone = phone
        self.headline = headline
        self.location = location
        self.middle_name = middle_name
        self.preferred_name = preferred_name
        self._touch()

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

    def set_job_search_preferences(self, preferences: JobSearchPreferences) -> None:
        """Replace what the candidate is looking for.

        A whole-value replace rather than per-field edits: preferences are a
        small set the candidate reviews together, and an empty
        `JobSearchPreferences` is the meaningful way to say "stop filtering" —
        which a merge-style update could not express.
        """
        if not isinstance(preferences, JobSearchPreferences):
            raise InvalidValueError(
                "set_job_search_preferences requires a JobSearchPreferences."
            )
        self.job_search_preferences = preferences
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

    # ---- Editing and removing list entries -----------------------------------
    #
    # The counterparts to the three `add_*` methods above. Until an editable
    # profile existed, a résumé parse could only ever append, so nothing needed
    # these — which is also why a mis-parsed job title was uncorrectable.
    #
    # Each `update_*` replaces an entry in place, keeping its position, and each
    # raises when the id names nothing. Refusing rather than appending matters:
    # an update against a stale id is a caller working from a list that has since
    # changed, and silently adding a second entry is the one outcome nobody
    # wants from a save button labelled "edit".

    def update_work_history(self, entry: WorkHistoryEntry) -> None:
        """Replace the work-history entry with the same id."""
        self.work_history[
            self._index_of(self.work_history, entry.id, "Work history")
        ] = entry
        self._touch()

    def remove_work_history(self, entry_id: str) -> None:
        """Remove the work-history entry with this id."""
        del self.work_history[
            self._index_of(self.work_history, entry_id, "Work history")
        ]
        self._touch()

    def update_education(self, entry: EducationEntry) -> None:
        """Replace the education entry with the same id."""
        self.education[self._index_of(self.education, entry.id, "Education")] = entry
        self._touch()

    def remove_education(self, entry_id: str) -> None:
        """Remove the education entry with this id."""
        del self.education[self._index_of(self.education, entry_id, "Education")]
        self._touch()

    def update_skill(self, skill: Skill) -> None:
        """Replace the skill with the same id.

        Re-checks the case-insensitive name rule `add_skill` enforces, against
        every *other* skill — so renaming "python" to "Java" when a "Java"
        already exists is refused, while renaming it to "Python" (its own name,
        recased) is not.
        """
        index = self._index_of(self.skills, skill.id, "Skill")
        renamed = skill.name.strip().lower()
        if any(
            other.name.strip().lower() == renamed
            for position, other in enumerate(self.skills)
            if position != index
        ):
            raise BusinessRuleViolationError(
                f"Skill '{skill.name}' already exists on this profile."
            )
        self.skills[index] = skill
        self._touch()

    def remove_skill(self, skill_id: str) -> None:
        """Remove the skill with this id."""
        del self.skills[self._index_of(self.skills, skill_id, "Skill")]
        self._touch()

    @staticmethod
    def _index_of(entries: Sequence[_HasEntryId], entry_id: str, label: str) -> int:
        """Where `entry_id` sits in `entries`, or raise.

        Generic over the three list types rather than accepting a union of them,
        because iterating a union widens the element to `object` and loses the
        `id` the lookup is for.
        """
        for index, entry in enumerate(entries):
            if entry.id == entry_id:
                return index
        raise ProfileEntryNotFoundError(label, entry_id)

    def _touch(self) -> None:
        self.updated_at = _utcnow()
