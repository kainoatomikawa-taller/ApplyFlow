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

    #: The provenance sources that count as the candidate *attesting* to this
    #: record, as opposed to it having been inferred on their behalf.
    #:
    #: `PARSED_RESUME` is deliberately absent. Every other fact on a profile
    #: is fine to read out of a resume — a job title extracted slightly wrong
    #: is a cosmetic error. A work-authorization status is not: it is a legal
    #: declaration the candidate signs their name to, and one inferred from
    #: prose ("authorized to work in the US" appearing in a summary line, or a
    #: model's reading of a visa mention) is a claim they never actually made.
    #: Autofilling from it would put a machine's inference on a legal form
    #: under the candidate's signature.
    ATTESTING_SOURCES: ClassVar[frozenset[ProvenanceSource]] = frozenset(
        {ProvenanceSource.USER_ENTERED, ProvenanceSource.ANSWER}
    )

    def __post_init__(self) -> None:
        if not isinstance(self.source, ProvenanceSource):
            raise InvalidValueError(
                "WorkAuthorization requires a valid ProvenanceSource."
            )

    @property
    def is_candidate_attested(self) -> bool:
        """Whether the candidate themselves stated this record.

        Only an attested record may be autofilled onto an application (see
        `decide_sensitive_field`). An unattested one is still stored, still
        usable for matching and filtering, and still shown to the candidate —
        it just cannot be asserted to an employer on their behalf until they
        confirm it.
        """
        return self.source in WorkAuthorization.ATTESTING_SOURCES
