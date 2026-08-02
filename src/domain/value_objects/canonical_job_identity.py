"""CanonicalJobIdentity — what makes two job records "the same role".

The one answer to "has the candidate already applied to this?"
------------------------------------------------------------------
A candidate does not apply to a row, they apply to a *role*: a company, a
title, a place. Two records can name that same role and share no identifier
at all — the posting was re-ingested under a new id, the same opening was
picked up from a second aggregator, the employer relisted it. So the tracker
cannot answer "already applied?" by comparing `job_posting_id`, and the
matching layer cannot suppress a re-application nudge without a notion of
identity that survives all three cases. This value object is that notion:
company + title + location, each collapsed by `normalize_text`.

Why `normalize_text` and not something fuzzier
----------------------------------------------
It is the *same* collapse Epic 02's ingestion dedup already uses to derive
`JobPosting.normalized_company` / `normalized_title` / `normalized_location`
(trimmed, lowercased, whitespace-collapsed). Reused rather than restated, so
two records Epic 02 considers duplicates can never be two different roles to
the tracker — a divergence between the two rules would show up as a candidate
being nudged to re-apply to a posting the ingest layer had already called a
duplicate of one they applied to.

Deliberately not fuzzy for the same reason Epic 02 is not: "Backend Engineer"
and "Backend Engineer II" are different roles, and a matcher loose enough to
merge them is also loose enough to hide a job the candidate has never applied
to. Suppression removes things from the candidate's view, so its failure mode
has to be showing one job too many, never hiding one.

Why `source` is *not* part of it
--------------------------------
Epic 02's dedup key is scoped to one source — it answers "did this feed
already give me this listing?", and the same opening arriving from Adzuna and
from Greenhouse is legitimately two rows. This identity answers a different
question: "is this the role I applied to?" Applying through one board means
the application is with the employer regardless of which feed surfaced it, so
the source is dropped here on purpose.

`location=None` stays its own value, exactly as it does in Epic 02's key: a
posting that names no location is not asserted to be the same role as one
that names Berlin. That errs toward showing a job rather than hiding one.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.exceptions import InvalidValueError
from src.domain.services.text_normalization import normalize_text


@dataclass(frozen=True)
class CanonicalJobIdentity:
    """A role's identity across records: normalized company + title +
    location. Frozen and hashable, so a candidate's applied-to set is a plain
    set lookup (see `AppliedJobIndex`).

    Build it with `of` rather than the constructor — `of` applies the
    normalization, and two identities are only comparable if both went
    through it.
    """

    company: str
    title: str
    location: str | None

    def __post_init__(self) -> None:
        if not self.company:
            raise InvalidValueError(
                "CanonicalJobIdentity requires a non-empty company — an "
                "identity missing one would collapse every company's roles "
                "with the same title into one."
            )
        if not self.title:
            raise InvalidValueError("CanonicalJobIdentity requires a non-empty title.")

    @classmethod
    def of(
        cls, *, company: str, title: str, location: str | None = None
    ) -> CanonicalJobIdentity:
        """Build an identity from display strings, normalizing each the way
        Epic 02's dedup keys are normalized.

        A location that is blank or whitespace-only is treated as absent
        rather than as an empty-string location — the two mean the same thing
        coming out of an aggregator, and letting them be different identities
        would make "already applied" depend on a stray space.
        """
        normalized_location = normalize_text(location) if location else None
        return cls(
            company=normalize_text(company),
            title=normalize_text(title),
            location=normalized_location or None,
        )
