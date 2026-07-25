"""ProvenanceBackedFact value object — one statement about a candidate,
paired with the `ProvenanceSource` that entitles ApplyFlow to assert it.

This is the unit of ground truth `ProvenanceGuard` validates generated
output against. `ProvenanceSource` documents the rule ("every generated
statement has to trace back to a `parsed_resume`, `user_entered`, or
`answer` fact already in the data model"); this type is what makes the
rule mechanically checkable, by refusing to exist without a source. A
plain fact string can't say where it came from, so a corpus of plain
strings can't prove anything about provenance — a corpus of these can.

Only facts the candidate's own data states become one. Derived aggregates
(a computed "N years of experience" total, for instance) are deliberately
not `ProvenanceBackedFact`s: nobody entered them, no resume stated them,
no answer supplied them, so there is no honest source to tag them with.
See `CandidateFactExtractor.extract_provenance_backed`.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.provenance_source import ProvenanceSource


@dataclass(frozen=True)
class ProvenanceBackedFact:
    """A candidate fact plus the provenance that backs it."""

    text: str
    source: ProvenanceSource

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise InvalidValueError("ProvenanceBackedFact text cannot be empty.")
        if not isinstance(self.source, ProvenanceSource):
            raise InvalidValueError(
                "ProvenanceBackedFact requires a valid ProvenanceSource."
            )
