"""EeoSelfIdentification value object — voluntary EEO self-ID data.

SENSITIVE: same category of data as `WorkAuthorization` — flagged here at
the domain level (`SENSITIVE = True`) and mirrored on the ORM columns (see
`EeoSelfIdentificationModel`) for Epic 07's encryption-at-rest work.

This entire record is optional at the `UserProfile` level
(`eeo_self_identification: EeoSelfIdentification | None = None`), and every
field of the record itself defaults to `None` ("not provided") rather than
any category enum member. Nothing in this codebase ever fills in a default
answer or infers one — a `RaceEthnicity`, `GenderIdentity`, etc. value only
ever appears here because a candidate explicitly chose it, including the
explicit `DECLINE_TO_SELF_IDENTIFY` option on every category.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.eeo_categories import (
    DisabilityStatus,
    GenderIdentity,
    RaceEthnicity,
    VeteranStatus,
)
from src.domain.value_objects.provenance_source import ProvenanceSource


@dataclass(frozen=True)
class EeoSelfIdentification:
    """A candidate's voluntary EEO self-identification answers."""

    SENSITIVE: ClassVar[bool] = True

    # Required even though every category below may be None: constructing
    # this record at all means the candidate went through the self-ID
    # flow (an `ANSWER`), so its own provenance is never optional.
    source: ProvenanceSource
    gender_identity: GenderIdentity | None = None
    race_ethnicity: RaceEthnicity | None = None
    veteran_status: VeteranStatus | None = None
    disability_status: DisabilityStatus | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, ProvenanceSource):
            raise InvalidValueError(
                "EeoSelfIdentification requires a valid ProvenanceSource."
            )
