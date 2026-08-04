"""EducationEntry entity — one program of study on a candidate's profile.

Owned by the `UserProfile` aggregate; it has no lifecycle of its own outside
of a profile.

Majors and minors are sequences rather than one `field_of_study` string, because
a double major is two facts about a candidate and joining them at the point of
entry throws away which is which. Minors are held separately for the same
reason: "minor in Economics" and "major in Economics" are different claims, and a
tailored resume that promotes one to the other is stating something untrue.

Application forms, on the other hand, almost always give one "field of study" box
— so `field_of_study` remains available as a derived single-string rendering of
the majors. It is a property, not stored state: one source of truth, no way for
the joined form and the structured list to drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.provenance_source import ProvenanceSource


def _clean_subjects(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    """Strip, drop blanks, and drop case-insensitive repeats, keeping order.

    Blank entries are dropped rather than rejected: an editor offering a row per
    subject will naturally produce an empty trailing one, and that is a UI
    artifact rather than something the candidate asserted. Repeats are dropped
    because listing the same major twice states nothing extra, and would be
    duplicated onto every form the value is written to.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise InvalidValueError(f"Each {label} must be a string.")
        subject = value.strip()
        if not subject:
            continue
        if subject.casefold() in seen:
            continue
        seen.add(subject.casefold())
        cleaned.append(subject)
    return tuple(cleaned)


@dataclass
class EducationEntry:
    """A single school/program attended by the candidate."""

    id: str
    institution_name: str
    degree: str
    source: ProvenanceSource
    #: Fields of study the candidate majored in — one entry for a single major,
    #: several for a double or triple major.
    majors: tuple[str, ...] = field(default_factory=tuple)
    #: Fields of study taken as a minor. Deliberately never merged into
    #: `majors`; see the module docstring.
    minors: tuple[str, ...] = field(default_factory=tuple)
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
        if not isinstance(self.source, ProvenanceSource):
            raise InvalidValueError("EducationEntry requires a valid ProvenanceSource.")
        self.majors = _clean_subjects(tuple(self.majors), "major")
        self.minors = _clean_subjects(tuple(self.minors), "minor")

    @property
    def field_of_study(self) -> str | None:
        """The majors as one string, for form boxes that ask for a single value.

        `None` rather than `""` when there are no majors, so a caller cannot tell
        "no majors on file" apart from any other absent optional value — the
        distinction the rest of the profile already relies on.
        """
        return ", ".join(self.majors) or None
