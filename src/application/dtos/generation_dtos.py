"""DTOs — input/output contracts for provenance-guarded document
generation (tailored resumes and cover letters)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GeneratedDocumentKind(StrEnum):
    """Which document a guarded generation run produced. Used to label
    audit-log entries so a violation can be traced to the flow that
    produced it."""

    TAILORED_RESUME = "tailored_resume"
    COVER_LETTER = "cover_letter"


@dataclass(frozen=True)
class GenerateTailoredResumeInput:
    user_id: str
    job_posting_id: str


@dataclass(frozen=True)
class GenerateCoverLetterInput:
    user_id: str
    job_posting_id: str


@dataclass(frozen=True)
class ProvenanceViolationOutput:
    """One assertion the guard removed, and the terms nothing in the
    candidate's provenance-backed data backed."""

    line: str
    unsupported_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GuardedDocumentOutput:
    """A generated document after the provenance guard has run.

    `content` is post-guard text only — there is no path that returns the
    raw model output, so a caller cannot accidentally ship an unvalidated
    draft. `backing_sources` names the provenance the surviving content
    traces to, and `violations` is what was taken out; an empty
    `violations` list means the model asserted nothing it couldn't
    support.
    """

    job_posting_id: str
    document_kind: str
    content: str
    backing_sources: list[str] = field(default_factory=list)
    violations: list[ProvenanceViolationOutput] = field(default_factory=list)
