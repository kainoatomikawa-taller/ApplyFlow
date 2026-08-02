"""AppliedJobIndex — the roles a candidate has already applied to, as a set
the matching layer can test a posting against.

The rule it encodes
-------------------
A job is "already applied to" when its `CanonicalJobIdentity` matches that of
any application in the candidate's tracker. Not the posting id: the tracker
records the role that was applied to, and the same role reappears in the
active job set under a new id every time it is re-ingested, relisted, or
picked up from a second aggregator. Matching on id would leave the candidate
nudged to re-apply to a job they already sent — the thing this exists to
prevent.

Why every application counts, whatever became of it
---------------------------------------------------
Status is deliberately not consulted. A rejection is the strongest possible
reason not to nudge someone to apply again, and a withdrawal is the candidate
saying they are not pursuing the role. "Applied and it went nowhere" is still
applied; re-applying to the same posting is a decision the candidate can make
deliberately from the tracker, not something the matcher should suggest.

Why a set built once, not a query per posting
---------------------------------------------
Ranking walks the whole active job set. Asking the repository per posting
would be one round trip per job, and the answer for the candidate does not
change during a run — so the caller loads the identities once and hands them
here. Identities are frozen and hashable, so the test itself is a hash lookup.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.domain.entities.job_posting import JobPosting
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.value_objects.canonical_job_identity import CanonicalJobIdentity


class AppliedJobIndex:
    """Which canonical roles a candidate has already applied to."""

    def __init__(self, identities: Iterable[CanonicalJobIdentity] = ()) -> None:
        self._identities: frozenset[CanonicalJobIdentity] = frozenset(identities)

    @classmethod
    def from_applications(
        cls, applications: Iterable[TrackedApplication]
    ) -> AppliedJobIndex:
        """Build the index from tracked application records."""
        return cls(application.canonical_identity for application in applications)

    def has_applied_to(self, job_posting: JobPosting) -> bool:
        """Whether this posting is a role the candidate already applied to."""
        return job_posting.canonical_identity in self._identities

    def __len__(self) -> int:
        """How many distinct roles the candidate has applied to — fewer than
        the number of applications when the same role was applied to twice."""
        return len(self._identities)
