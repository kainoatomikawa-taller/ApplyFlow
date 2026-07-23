"""WorkAuthorization value object — a candidate's work-authorization/citizenship data.

SENSITIVE: this is exactly the category of data Epic 07 (encryption) exists
to protect. `SENSITIVE = True` is a domain-level fact about this data (not
an infrastructure detail) so any code path handling a `WorkAuthorization` —
repository, mapper, future API serializer — can check `WorkAuthorization.SENSITIVE`
before deciding how to store, log, or transmit it. The infrastructure layer
mirrors this flag on the corresponding ORM columns (see
`src/infrastructure/persistence/models.py::WorkAuthorizationModel`) so it is
also visible at the schema level for Epic 07's encryption-at-rest work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)


@dataclass(frozen=True)
class WorkAuthorization:
    """A candidate's self-reported work-authorization/citizenship details."""

    SENSITIVE: ClassVar[bool] = True

    status: WorkAuthorizationStatus
    source: ProvenanceSource
    citizenship_country: str | None = None
    visa_type: str | None = None
    requires_sponsorship: bool | None = None
    details: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, ProvenanceSource):
            raise InvalidValueError(
                "WorkAuthorization requires a valid ProvenanceSource."
            )
