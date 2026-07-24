"""JobRequirements value object — a job posting's structured requirement
attributes (Epic 03), extracted from its free-text description.

Every field is optional: a description that doesn't state (or states only
ambiguously) a given attribute must leave it `None`/empty here rather than
have the extractor guess — see `JobRequirementsExtractorPort`, the only
producer of this value object. `__post_init__` only rejects internally
inconsistent data (a negative year count, a max below its min); it never
requires any field to be present.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.remote_type import RemoteType
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)


@dataclass(frozen=True)
class JobRequirements:
    """Structured requirement attributes read from a job posting's
    description. Feeds downstream classification and scoring."""

    degree_level: DegreeLevel | None = None
    #: Whether the stated `degree_level` is mandatory (True), merely
    #: preferred/nice-to-have (False), or the text doesn't say (None).
    degree_required: bool | None = None
    clearance_level: ClearanceLevel | None = None
    clearance_required: bool | None = None
    remote_type: RemoteType | None = None
    #: Specific eligible locations/constraints called out in the text
    #: (e.g. "United States", "within 4 hours of EST") — free text since
    #: postings phrase these too inconsistently for a fixed enum.
    locations: tuple[str, ...] = field(default_factory=tuple)
    #: The minimum work-authorization status the employer states it will
    #: accept (e.g. REQUIRES_SPONSORSHIP when the posting says sponsorship
    #: is available, CITIZEN when it demands U.S. citizenship).
    work_authorization: WorkAuthorizationStatus | None = None
    min_years_experience: int | None = None
    max_years_experience: int | None = None
    required_skills: tuple[str, ...] = field(default_factory=tuple)
    preferred_skills: tuple[str, ...] = field(default_factory=tuple)
    #: Any other stated preference that doesn't fit the fields above.
    preferences: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.min_years_experience is not None and self.min_years_experience < 0:
            raise InvalidValueError(
                "JobRequirements.min_years_experience cannot be negative."
            )
        if self.max_years_experience is not None and self.max_years_experience < 0:
            raise InvalidValueError(
                "JobRequirements.max_years_experience cannot be negative."
            )
        if (
            self.min_years_experience is not None
            and self.max_years_experience is not None
            and self.min_years_experience > self.max_years_experience
        ):
            raise InvalidValueError(
                "JobRequirements.min_years_experience cannot exceed "
                "max_years_experience."
            )
