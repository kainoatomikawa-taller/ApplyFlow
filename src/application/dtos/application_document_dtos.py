"""DTOs — input/output contracts for reading stored sent-document
snapshots (see `ApplicationDocument`).

Two output shapes, deliberately: the summary carries everything needed to
*list* what was sent, and only the single-document read carries `content`.
A tracker screen listing thirty applications has no use for thirty full
resumes, and shipping them anyway would spread the most PII-dense text in
the system across every list response for no benefit. `content_sha256` is on
both, so a caller can tell two versions apart, or confirm the document it
already holds is the stored one, without fetching the text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class GetApplicationDocumentInput:
    user_id: str
    document_id: str


@dataclass(frozen=True)
class GetLatestApplicationDocumentInput:
    """Ask for the newest stored version of one kind of document for a job.

    `document_kind` is a plain string at this boundary (the interface layer
    passes through whatever arrived on the request); the use case is what
    resolves it to a `GeneratedDocumentKind` or rejects it.
    """

    user_id: str
    job_posting_id: str
    document_kind: str


@dataclass(frozen=True)
class ListApplicationDocumentsInput:
    """List a candidate's snapshots, newest first — every job when
    `job_posting_id` is None, one job's history when it is set."""

    user_id: str
    job_posting_id: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class ApplicationDocumentSummaryOutput:
    """One stored snapshot without its text."""

    id: str
    job_posting_id: str
    document_kind: str
    version: int
    content_sha256: str
    created_at: datetime
    backing_sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ApplicationDocumentOutput:
    """One stored snapshot, including the exact text that was produced."""

    id: str
    job_posting_id: str
    document_kind: str
    version: int
    content: str
    content_sha256: str
    created_at: datetime
    backing_sources: list[str] = field(default_factory=list)
