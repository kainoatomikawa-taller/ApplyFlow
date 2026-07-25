"""DTOs — input/output contracts for provenance-guarded document
generation (tailored resumes and cover letters).

`document_kind` is carried as a plain string on the way out, while the
generation flows work with `GeneratedDocumentKind`
(`src/domain/value_objects/`). The enum lives in the domain layer rather than
here because stored snapshots are labeled with it — see
`ApplicationDocument` — and serializing it as a string keeps this boundary
from making a caller import a domain type to read a response.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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

    `document_id`/`version` identify the immutable snapshot this exact
    content was stored as (see `ApplicationDocument`). They are not optional
    extras: the content in this DTO is already archived by the time a caller
    sees it, so the caller can hand the id to the tracker or interview prep
    instead of holding the text or asking for it to be generated again.
    """

    document_id: str
    job_posting_id: str
    document_kind: str
    content: str
    version: int
    backing_sources: list[str] = field(default_factory=list)
    violations: list[ProvenanceViolationOutput] = field(default_factory=list)


@dataclass(frozen=True)
class ResumeSectionOutput:
    """One section of the resume as an ATS parser will read it."""

    heading: str
    lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AtsSafetyViolationOutput:
    """One ATS-safety rule the finished resume breaks, named so a caller can
    say which and why (see `AtsSafetyValidator`)."""

    rule: str
    detail: str
    line: str
    line_number: int


@dataclass(frozen=True)
class ResumeExportsOutput:
    """The three renderings of one tailored resume, all derived from the same
    guarded text so they cannot disagree.

    `text` is that text verbatim — the plain-text export a candidate pastes
    into an application form. `contact_lines`/`sections` are the same text
    parsed the way an ATS reads it, which is the structured export. `pdf` is
    the rendered file as raw bytes; base64 or any other transport encoding is
    the interface layer's business, not this DTO's.
    """

    text: str
    pdf: bytes
    contact_lines: list[str] = field(default_factory=list)
    sections: list[ResumeSectionOutput] = field(default_factory=list)


@dataclass(frozen=True)
class TailoredResumeOutput:
    """A tailored resume: the guarded document, its exports, and the ATS
    safety check on the finished article.

    `document` is composed rather than flattened so the cover-letter flow can
    keep returning a plain `GuardedDocumentOutput` — the provenance contract
    is identical for both, and only the resume has files and a layout to
    answer for. `ats_safety_violations` should be empty; anything in it means
    the formatter let something through (see `AtsSafetyValidator`).
    """

    document: GuardedDocumentOutput
    exports: ResumeExportsOutput
    ats_safety_violations: list[AtsSafetyViolationOutput] = field(default_factory=list)
