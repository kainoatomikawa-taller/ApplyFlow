"""GeneratedDocumentKind value object — which document a guarded
generation run produced.

This lives in the domain layer because it labels stored data, not just a
use case's output: an `ApplicationDocument` snapshot is only interpretable
next to the kind of document it holds, and the domain cannot reach into
`application/` for the enum. The generation flows and the audit log use the
same member set, so a kind can be traced from the run that produced it to
the row that keeps it without two definitions drifting apart.

Adding a member is a data-model change, not a labeling convenience: every
stored snapshot carries one of these strings, so a renamed member
invalidates existing rows.
"""

from __future__ import annotations

from enum import StrEnum


class GeneratedDocumentKind(StrEnum):
    """A kind of provenance-guarded document ApplyFlow generates."""

    TAILORED_RESUME = "tailored_resume"
    COVER_LETTER = "cover_letter"
