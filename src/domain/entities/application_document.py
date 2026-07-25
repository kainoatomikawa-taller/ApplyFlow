"""ApplicationDocument entity — the exact resume or cover letter produced
for one job, kept verbatim so it never has to be produced again.

Why this exists
---------------
Everything downstream of generation needs the document the candidate
actually sent, not a fresh one that resembles it. The tracker (Epic 06) has
to show what went out; interview prep has to rehearse against the claims
that were actually made. Re-running the generator would answer a different
question: it reads today's profile through today's model, so it can quietly
produce a document the employer never saw — and then prep the candidate for
claims they never made. A snapshot removes that whole class of drift by
making the sent document a stored fact rather than a re-derivation.

Immutable, and not merely by convention
---------------------------------------
The entity is a frozen dataclass, its `backing_sources` is a tuple rather
than a list, and `ApplicationDocumentRepository` deliberately has no
`update` — so there is no in-process way to alter a snapshot and no
persistence method that would carry an alteration to the database. Editing
what was sent is not a feature this store withholds; it is a statement that
would be false.

`content_sha256` closes the remaining gap. In-process immutability says
nothing about a row changed by a migration, a manual `UPDATE`, or a bad
mapping, so the digest is written alongside the content and verified on the
way back out (`ensure_content_matches`). A snapshot that no longer hashes to
its recorded digest is not silently returned as authentic.

Versions are per job, not global
--------------------------------
A candidate can regenerate a resume for the same posting — after filling a
gap, or after their profile grows. Each run is stored as its own version
rather than overwriting the last, numbered within its
(user, job posting, kind) so "version 2 of the cover letter for this job"
means something on its own. The newest version is what the latest
submission carried; the earlier ones stay because an application already
sent cannot be un-sent.

SENSITIVE: a tailored resume carries the candidate's contact details and
full work history, and a cover letter is *built from* their remembered
answers (`AnswerMemory`, which is flagged sensitive for exactly this
reason — an answer can just as easily be about salary, an accommodation, or
visa status as anything innocuous). A snapshot therefore inherits the
strictest classification of its inputs and never the mildest: flagged
sensitive here and on `ApplicationDocumentModel`, and never logged — log
the snapshot's `id` instead.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from src.domain.exceptions import DocumentSnapshotIntegrityError, InvalidValueError
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ApplicationDocument:
    """One immutable snapshot of a document produced for one job posting."""

    SENSITIVE: ClassVar[bool] = True
    #: Version numbers are 1-based within a (user, job posting, kind), so
    #: "version 1" always reads as "the first one produced for this job"
    #: rather than "an unversioned row".
    FIRST_VERSION: ClassVar[int] = 1

    id: str
    user_id: str
    job_posting_id: str
    document_kind: GeneratedDocumentKind
    content: str
    version: int
    #: The provenance the content traces to (see `ProvenanceGuard`).
    #: Required to be non-empty — see `__post_init__`.
    backing_sources: tuple[ProvenanceSource, ...] = ()
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("ApplicationDocument requires a non-empty id.")
        if not self.user_id:
            raise InvalidValueError("ApplicationDocument requires a non-empty user_id.")
        if not self.job_posting_id:
            raise InvalidValueError(
                "ApplicationDocument requires a non-empty job_posting_id."
            )
        if not isinstance(self.document_kind, GeneratedDocumentKind):
            raise InvalidValueError(
                "ApplicationDocument requires a valid GeneratedDocumentKind."
            )
        if not self.content.strip():
            raise InvalidValueError(
                "ApplicationDocument.content cannot be empty — a snapshot of "
                "nothing records nothing about what was sent."
            )
        if self.version < ApplicationDocument.FIRST_VERSION:
            raise InvalidValueError(
                "ApplicationDocument.version must be "
                f"{ApplicationDocument.FIRST_VERSION} or greater."
            )
        # A tuple, not any sequence: a list here would be a mutable field on
        # a frozen entity, which is precisely the immutability this class
        # claims to have.
        if not isinstance(self.backing_sources, tuple):
            raise InvalidValueError(
                "ApplicationDocument.backing_sources must be a tuple."
            )
        if not self.backing_sources:
            raise InvalidValueError(
                "ApplicationDocument requires at least one backing provenance "
                "source — only attested content is ever stored as sent."
            )
        if not all(
            isinstance(source, ProvenanceSource) for source in self.backing_sources
        ):
            raise InvalidValueError(
                "ApplicationDocument.backing_sources must contain only "
                "ProvenanceSource members."
            )

    # ---- Construction --------------------------------------------------------

    @classmethod
    def snapshot(
        cls,
        *,
        document_id: str,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
        content: str,
        backing_sources: tuple[ProvenanceSource, ...],
        stored_versions: int = 0,
    ) -> ApplicationDocument:
        """Capture `content` as the next version for this job and kind.

        `stored_versions` is how many snapshots of this kind already exist
        for this (user, job posting) — the caller reads it through the
        repository, and the numbering rule stays here so no call site
        invents its own.
        """
        if stored_versions < 0:
            raise InvalidValueError("stored_versions cannot be negative.")
        return cls(
            id=document_id,
            user_id=user_id,
            job_posting_id=job_posting_id,
            document_kind=document_kind,
            content=content,
            version=stored_versions + cls.FIRST_VERSION,
            backing_sources=backing_sources,
        )

    # ---- Behaviors -----------------------------------------------------------

    @property
    def content_sha256(self) -> str:
        """The digest of this snapshot's content.

        Computed rather than stored on the entity so it can never disagree
        with the content it describes. Persistence writes it as its own
        column, which is what makes an out-of-band edit to a stored row
        detectable (see `ensure_content_matches`).
        """
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    def ensure_content_matches(self, digest: str) -> None:
        """Raise unless `digest` is this snapshot's own content digest.

        Called when a snapshot is read back, so content that changed after
        it was written surfaces as an integrity failure instead of being
        handed to the tracker or interview prep as the document that was
        sent.
        """
        if digest != self.content_sha256:
            raise DocumentSnapshotIntegrityError(
                document_id=self.id,
                expected_digest=digest,
                actual_digest=self.content_sha256,
            )

    @property
    def is_tailored_resume(self) -> bool:
        return self.document_kind is GeneratedDocumentKind.TAILORED_RESUME

    @property
    def is_cover_letter(self) -> bool:
        return self.document_kind is GeneratedDocumentKind.COVER_LETTER
