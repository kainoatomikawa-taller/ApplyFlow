"""SQLAlchemy ORM models.

ORM models live in infrastructure and MUST NOT leak into domain or
application. Mapping to/from domain entities happens in the repository.

Encryption at rest (Epic 07)
----------------------------
Every column tagged `_SENSITIVE_COLUMN_INFO` below is declared with one of the
encrypted column types from `encrypted_types.py`, so its value is AES-256-GCM
ciphertext in the database and plaintext only in a Python process that has
declared an access scope (see `security/sensitive_access.py`). The tag and the
encryption are kept in lockstep by a test that walks this metadata
(`tests/infrastructure/test_sensitive_column_coverage.py`) and fails if a
sensitive-flagged column is stored in the clear — so adding a column here and
flagging it is enough to be told that it also needs encrypting.

Two consequences worth knowing before writing a query against one of these:

- They cannot be filtered, ordered, or grouped by in SQL. The database holds
  ciphertext and cannot compare it. `job_applications.candidate_email` is the
  one column that still needs an equality lookup, and it has a blind-index
  companion column for the database to compare instead.
- They are stored as `Text` regardless of what they hold, because ciphertext
  has no length or shape. The former `Boolean`/`JSON`/`String(n)` types survive
  as Python-side types on the encrypted column, not as database constraints.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.database import Base
from src.infrastructure.persistence.encrypted_types import (
    EncryptedBoolean,
    EncryptedJson,
    EncryptedString,
)

# Mirrors the `SENSITIVE = True` flag on the domain value objects
# (`WorkAuthorization`, `EeoSelfIdentification`) at the schema level: the
# machine-readable record of which columns hold data that must be encrypted at
# rest and read only through an authorized path. `info=` is what the coverage
# test queries; `comment=` is what someone reading `\d` or a migration sees.
_SENSITIVE_COLUMN_INFO = {"sensitive": True}
_SENSITIVE_COMMENT = (
    "SENSITIVE: AES-256-GCM encrypted at rest (Epic 07). Not queryable by "
    "value; decrypts only inside a declared access scope. Never log."
)

# Every stored fact carries a provenance tag mirroring the domain's
# `ProvenanceSource` — see that module for the full Epic 04 contract.
# `String(16)` comfortably fits the longest member ("parsed_resume").
_PROVENANCE_COMMENT = (
    "Fact provenance: parsed_resume | user_entered | answer. "
    "Required — see src/domain/value_objects/provenance_source.py."
)


class JobApplicationModel(Base):
    """A candidate's application to one role.

    SENSITIVE: `candidate_email` is contact information, and it is the one
    encrypted column in this schema that still has to be looked up by exact
    value (`list_by_candidate`). Encryption is randomized, so the ciphertext
    cannot be compared — `candidate_email_bidx` carries a keyed digest of the
    same address for the database to index and match on instead. The
    repository maintains the pair; nothing else should write either column.
    """

    __tablename__ = "job_applications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_email: Mapped[str] = mapped_column(
        EncryptedString("job_applications.candidate_email"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    #: Keyed HMAC of the lowercased address — see `FieldCipher.blind_index`.
    #: Indexed, and the only thing `WHERE candidate_email = ?` can become. Not
    #: itself sensitive in the encrypt-at-rest sense: it is one-way and keyed,
    #: so it reveals no address. What it does reveal is which rows share one,
    #: which is the whole point of having it.
    candidate_email_bidx: Mapped[str] = mapped_column(
        String(64),
        index=True,
        comment=(
            "Blind index (keyed HMAC-SHA256) of candidate_email — the lookup "
            "key for the encrypted column. See "
            "src/infrastructure/security/field_cipher.py."
        ),
    )
    company_name: Mapped[str] = mapped_column(String(255))
    role_title: Mapped[str] = mapped_column(String(255))
    job_description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: SENSITIVE. A cover letter written from this candidate's profile — their
    #: name, contact details, and employment history in prose. Encrypted as of
    #: migration 0023; the hardening pass found it in the clear while
    #: `application_documents.content`, which holds the same class of document,
    #: was encrypted. The reasoning on that column applies verbatim here: a
    #: document derived from sensitive inputs inherits their classification
    #: rather than a milder one. This column is the Epic 00/01 predecessor of
    #: that table and was simply missed when the flags were drawn up.
    tailored_cover_letter: Mapped[str | None] = mapped_column(
        EncryptedString("job_applications.tailored_cover_letter"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobPostingModel(Base):
    """A single job listing, normalized from an aggregator source
    (LinkedIn, Indeed, Greenhouse, ...) into ApplyFlow's internal shape.

    `normalized_company`/`normalized_title`/`normalized_location` are
    derived, indexed copies of `company`/`title`/`location` — the dedup
    key fields matching/dedup logic queries against instead of
    re-normalizing on every read.

    `status`/`last_checked_at`/`consecutive_link_failures` back the
    stale-posting / dead-apply-link sweep (see `DetectStaleJobPostings`) —
    `status` is indexed alone (fast "active job set" reads) and together
    with `last_checked_at` (the sweep's "what's due for a check" query).
    """

    __tablename__ = "job_postings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text)
    apply_url: Mapped[str] = mapped_column(String(2048))
    salary: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    posted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    normalized_company: Mapped[str] = mapped_column(String(255), index=True)
    normalized_title: Mapped[str] = mapped_column(String(255), index=True)
    normalized_location: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_link_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Epic 03's structured requirement extraction result — NULL until that
    # pass has run for this posting (see `list_missing_requirements`, the
    # query the extraction sweep uses to find postings still needing it).
    requirements: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class ResolvedCompanyBoardModel(Base):
    """A permanent cache entry: which ATS platform + board token a
    company's public job listings are hosted on, discovered once via the
    search API. `normalized_company` is unique — once a company has a row
    here, `AtsListingResolver` never searches for its board again. Does
    NOT cache any job-specific apply URL/description — those are always
    looked up fresh per listing against the (free, unauthenticated) board
    referenced here.
    """

    __tablename__ = "resolved_company_boards"

    normalized_company: Mapped[str] = mapped_column(String(255), primary_key=True)
    company: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(32))
    board_token: Mapped[str] = mapped_column(String(255))
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserProfileModel(Base):
    """A candidate's profile row: contact details plus the provenance of each.

    SENSITIVE: the contact columns — name, email, phone, location, and the
    postal address — are encrypted at rest. Epic 01 left them unflagged while
    flagging citizenship and EEO, on the reading that contact details are the
    ordinary, freely-given part of a profile. Epic 07 flags them, because
    "ordinary" describes how willingly a candidate hands them to an employer,
    not what they are in a stolen database: a name, home address, phone number
    and email for every candidate on the platform is the identifying half of
    every other sensitive fact stored here, and the acceptance criteria for
    this work name contact info first.

    `user_id` stays in the clear, and has to: it is the tenancy key every
    repository filters on and every index is built from, it is issued by the
    auth provider rather than by the candidate, and it identifies a row without
    describing a person. `headline` is also left in the clear — it is a
    self-written professional tagline, the same category of data as the work
    history and skills in the child tables, none of which this epic encrypts.
    """

    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(
        EncryptedString("user_profiles.full_name"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    email: Mapped[str] = mapped_column(
        EncryptedString("user_profiles.email"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    # Provenance for full_name/email/phone/headline/location as a bundle —
    # see UserProfile's module docstring for why. Always required: those
    # fields are always present once a profile exists. Not itself sensitive:
    # "the candidate typed this" describes the fact without disclosing it.
    contact_source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)
    phone: Mapped[str | None] = mapped_column(
        EncryptedString("user_profiles.phone"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(
        EncryptedString("user_profiles.location"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )

    # Contact info — postal address. Encrypted at rest per the class docstring.
    street_address: Mapped[str | None] = mapped_column(
        EncryptedString("user_profiles.street_address"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    city: Mapped[str | None] = mapped_column(
        EncryptedString("user_profiles.city"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    state_or_region: Mapped[str | None] = mapped_column(
        EncryptedString("user_profiles.state_or_region"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    postal_code: Mapped[str | None] = mapped_column(
        EncryptedString("user_profiles.postal_code"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    country: Mapped[str | None] = mapped_column(
        EncryptedString("user_profiles.country"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    # Nullable: only required once the address above actually has data —
    # enforced by UserProfile._validate_optional_source, not by the schema.
    address_source: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment=_PROVENANCE_COMMENT
    )

    # Links — portfolio/LinkedIn/GitHub. Not sensitive-flagged: each is a
    # public profile the candidate publishes deliberately.
    portfolio_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Nullable for the same reason as address_source.
    links_source: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment=_PROVENANCE_COMMENT
    )

    # Candidate-held clearance/degree — compared against a job posting's
    # requirements by `HardDisqualifierFilter`. Nullable: an unstated value
    # means "unknown", never "candidate has none" (see UserProfile).
    clearance_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    highest_degree: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    work_history: Mapped[list[WorkHistoryModel]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="WorkHistoryModel.start_date.desc()",
    )
    education: Mapped[list[EducationModel]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="EducationModel.start_date.desc()",
    )
    skills: Mapped[list[SkillModel]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="SkillModel.name",
    )
    # One-to-one, optional — see WorkAuthorizationModel/EeoSelfIdentificationModel
    # docstrings for why these live in their own sensitive-flagged tables.
    work_authorization: Mapped[WorkAuthorizationModel | None] = relationship(
        back_populates="profile", cascade="all, delete-orphan", uselist=False
    )
    eeo_self_identification: Mapped[EeoSelfIdentificationModel | None] = relationship(
        back_populates="profile", cascade="all, delete-orphan", uselist=False
    )


class ResumeModel(Base):
    """A candidate's uploaded resume: metadata + extracted text.

    Raw file bytes live outside the database (see `FileStoragePort` /
    `LocalFileStorage`) — `storage_key` is the only link between this row
    and the file on disk.

    SENSITIVE: `extracted_text` is the candidate's whole resume as text, which
    means it contains every contact detail on `user_profiles` and then some, and
    `original_filename` is routinely the candidate's own name. Both are
    encrypted at rest, on the same reasoning that encrypts
    `application_documents.content`: the derived document is protected, so the
    source it was derived from cannot be left in the clear beside it.

    The bytes on disk are a separate matter and are NOT encrypted by this epic
    — `LocalFileStorage` addresses them by an opaque server-generated key, so
    the storage directory discloses nothing by itself, but a reader of that
    directory reads resumes. Encrypting the blob store is the next increment;
    it is called out in docs/decisions/0002-encryption-at-rest.md rather than
    left implied.
    """

    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str] = mapped_column(
        EncryptedString("resumes.original_filename"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    extracted_text: Mapped[str] = mapped_column(
        EncryptedString("resumes.extracted_text"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnswerMemoryModel(Base):
    """A candidate's remembered answer to an application question, plus the
    embedding of its question text — the foundation for semantic retrieval
    (matching a future application's questions against ones already
    answered).

    SENSITIVE: unlike `WorkAuthorizationModel`/`EeoSelfIdentificationModel`,
    this table has no fixed set of columns per topic — `question_text` and
    `answer_text` can be about anything an application asked, so they can
    just as easily contain a salary expectation, a disability
    accommodation, or a visa/citizenship detail as something innocuous.
    Every column (including the embedding, which is derived from the
    question text) is flagged sensitive here as the conservative default,
    mirroring `AnswerMemory.SENSITIVE` in the domain layer, until Epic 07
    has a finer-grained classification.
    """

    __tablename__ = "answer_memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    question_text: Mapped[str] = mapped_column(
        EncryptedString("answer_memories.question_text"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    answer_text: Mapped[str] = mapped_column(
        EncryptedString("answer_memories.answer_text"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    # An encrypted JSON array of floats rather than a pgvector column: this
    # ticket only covers storage, not similarity search, and pgvector
    # isn't a dependency yet — a future retrieval epic can migrate this
    # column once it needs indexed nearest-neighbor queries. When it does,
    # note that it will be choosing between an indexed nearest-neighbour
    # search and this encryption: an embedding is a reversible-enough
    # projection of the question text that indexing it in the clear
    # partially undoes encrypting the text itself.
    embedding: Mapped[list[float]] = mapped_column(
        EncryptedJson("answer_memories.embedding"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationDocumentModel(Base):
    """The exact resume or cover letter produced for one job posting, kept
    verbatim so the tracker (Epic 06) and interview prep read what was sent
    instead of regenerating something like it.

    Write-once: nothing updates a row here. Regeneration inserts the next
    `version` for the same (`user_id`, `job_posting_id`, `document_kind`) —
    the unique constraint below is what makes two rows claiming to be the
    same version a database error rather than an ambiguity the tracker has
    to guess about. See `ApplicationDocument` for the full contract.

    `content_sha256` is the digest of `content` as written. It is verified on
    read (`SqlAlchemyApplicationDocumentRepository`), so content altered by a
    migration, a manual `UPDATE`, or a mapping bug surfaces instead of being
    served as the authentic sent document.

    The foreign key is `ON DELETE RESTRICT`, not `CASCADE`: a snapshot states
    what was actually sent to an employer, so it must not disappear as a side
    effect of pruning job postings. Removing these rows has to be a
    deliberate act against this table.

    SENSITIVE: `content` is a full tailored resume (contact details, complete
    work history) or a cover letter written from the candidate's remembered
    answers — and `AnswerMemoryModel` is flagged sensitive precisely because
    an answer may concern salary, an accommodation, or visa status. A
    document derived from those inputs inherits their classification rather
    than a milder one. Never log `content`; log `id` and `content_sha256`.
    """

    __tablename__ = "application_documents"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "job_posting_id",
            "document_kind",
            "version",
            name="uq_application_documents_version",
        ),
        # The tracker's feed: a candidate's snapshots across every job,
        # newest first. The unique constraint above already serves the
        # per-job and per-job-and-kind lookups.
        Index(
            "ix_application_documents_user_id_created_at",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    job_posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="RESTRICT"), index=True
    )
    document_kind: Mapped[str] = mapped_column(
        String(32),
        comment=(
            "Generated document kind: tailored_resume | cover_letter. "
            "See src/domain/value_objects/generated_document_kind.py."
        ),
    )
    content: Mapped[str] = mapped_column(
        EncryptedString("application_documents.content"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    #: Hex sha256 of the *plaintext* `content` — integrity, not identity. Not
    #: sensitive: a digest reveals nothing about the document it describes.
    #: Deliberately still the digest of the plaintext now that the column is
    #: encrypted, because what it exists to detect is content that changed
    #: (a migration, a manual `UPDATE`, a mapping bug), and encryption is
    #: randomized — digesting the ciphertext would differ on every rewrite of
    #: identical content and match nothing on read.
    content_sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    #: The provenance the content traces to, mirroring the domain's
    #: `ProvenanceSource` — a JSON array because a document is normally
    #: backed by several sources at once, unlike a single stored fact.
    backing_sources: Mapped[list[str]] = mapped_column(
        JSON, comment=_PROVENANCE_COMMENT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TrackedApplicationModel(Base):
    """One application the candidate actually sent — the tracker's spine. See
    `TrackedApplication` for the full contract.

    Every foreign key here is `ON DELETE RESTRICT`, matching
    `application_documents` rather than `application_reviews`/
    `portal_handoffs`. The distinction those tables draw is between an
    application *in flight* (worthless once its posting is gone, so CASCADE)
    and the archived record of one that was *sent* (a real event that must
    outlive the posting being pruned, so RESTRICT). This table is squarely the
    second. Pruning a posting a candidate applied to has to be a deliberate act
    against this row, not a side effect.

    `resume_document_id` / `cover_letter_document_id` point at
    `application_documents` — the exact snapshots that went to the employer,
    not the text of them. A `TEXT` column here would be a second copy free to
    drift from the row that is supposed to be authoritative, which is the
    failure `ApplicationDocument` exists to prevent. Note what the FK cannot
    check: that the referenced row is the right *kind* of document and belongs
    to this candidate and posting. Any `application_documents.id` satisfies the
    constraint, so that check lives in `TrackedApplication.record_sent`.

    `company_name`/`role_title`/`job_location` are copied from the posting at
    record time rather than read through `job_posting_id` on every query. A
    posting is a live row — re-ingested, re-normalized, retitled, eventually
    stale — and this one states what the candidate applied to *then*. The same
    three columns are the canonical role identity the matching layer suppresses
    already-applied jobs on, which is the other reason they are snapshotted:
    the answer has to survive the posting being pruned or relisted under a new
    id, and a join would lose it in exactly those cases.

    No unique constraint on (`user_id`, `job_posting_id`): applying to the same
    posting twice is two real events, each with its own date, documents, and
    outcome. Same reasoning as the submitted rows in `application_reviews`.

    Not sensitive. A role, a company, and a status carry nothing that
    `work_authorizations` or `answer_memories` do — the sensitive material sits
    in the documents this row references, behind their own flags. Which is why
    these columns are ids: this row stays loggable.
    """

    __tablename__ = "tracked_applications"
    __table_args__ = (
        # What makes logging a submission idempotent, and the reason it is a
        # constraint rather than a check in the service: two concurrent
        # requests from a double-clicked submit button can both pass a
        # "does it already exist?" read, and only the database can refuse the
        # second write. The logger catches this and returns the row that won.
        UniqueConstraint(
            "user_id",
            "submission_key",
            name="uq_tracked_applications_submission_key",
        ),
        # The tracker's feed: a candidate's applications, most recent first.
        Index(
            "ix_tracked_applications_user_id_applied_at",
            "user_id",
            "applied_at",
        ),
        # "What is still live?" — the open-applications view filters on status
        # before it orders, so the pair is worth its own index.
        Index("ix_tracked_applications_user_id_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    job_posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="RESTRICT"), index=True
    )
    #: Identifies the submission event this row was logged from — in practice
    #: the id of the submitted review. Unique per candidate (see
    #: `__table_args__`): that constraint is the idempotency guarantee, not an
    #: incidental index. Also answers "which submission produced this row?"
    #: without a second table.
    submission_key: Mapped[str] = mapped_column(
        String(128),
        comment=(
            "The submission event this row was logged from (in practice the "
            "submitted review's id). Unique per candidate — this is the "
            "idempotency guarantee for submission logging."
        ),
    )
    #: Snapshotted from the posting — see the class docstring.
    company_name: Mapped[str] = mapped_column(String(255))
    role_title: Mapped[str] = mapped_column(String(255))
    #: Snapshotted too, and the third component of the role identity the
    #: matching layer suppresses re-application nudges on (company + title +
    #: location — see `CanonicalJobIdentity`). Nullable: plenty of postings
    #: name no location, and rows written before this column existed have
    #: none either.
    job_location: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment=(
            "The posting's location as of send time. With company_name and "
            "role_title this forms the canonical role identity that keeps "
            "already-applied jobs out of the candidate's matches — see "
            "src/domain/value_objects/canonical_job_identity.py."
        ),
    )
    #: When the application was sent. Not nullable: this row exists because it
    #: was, and a tracker whose "date applied" could be NULL would need a
    #: branch in every reader for applications that were never applications.
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(32),
        comment=(
            "Application lifecycle: applied | interviewing | offer | rejected "
            "| withdrawn. Never 'draft' — an application still being prepared "
            "is an application_reviews row. See "
            "src/domain/value_objects/application_status.py."
        ),
    )
    #: The archived resume that went out. Required — an application ApplyFlow
    #: sent always carried one.
    resume_document_id: Mapped[str] = mapped_column(
        ForeignKey("application_documents.id", ondelete="RESTRICT"), index=True
    )
    #: The archived cover letter, when the posting asked for one. Nullable
    #: because plenty of forms do not ask.
    cover_letter_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("application_documents.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationStatusEventModel(Base):
    """One recorded status change on a tracked application — see
    `ApplicationStatusChange`.

    A child table rather than a JSON column on `tracked_applications`, because
    this history is queried, not just displayed: "which applications reached an
    interview?" and "how long do replies take?" are both aggregate questions
    over these rows, and neither is expressible against a JSON blob without
    reading every application first.

    Keyed by (`tracked_application_id`, `sequence`) with no surrogate id. A
    status change has no identity of its own — it is identified by the
    application it belongs to and its position in that application's history,
    which is exactly what the domain's value object models. `sequence` is
    0-based and gap-free, so the primary key doubles as the ordering: two
    changes recorded in the same clock tick still have a definite order, which
    `changed_at` alone could not give them.

    `ON DELETE CASCADE`, unlike every other foreign key on the tracker. This is
    the one relationship here that is genuinely a part-of rather than a
    reference-to: history without its application is unreadable, so it goes
    when the application does. The application itself is still protected from a
    posting being pruned by the RESTRICT on `tracked_applications`.

    Append-only in practice. Nothing in the data-access layer updates or
    deletes a row here — `SqlAlchemyTrackedApplicationRepository.update`
    inserts the entries it has not yet stored and leaves the rest untouched —
    because a status change is a thing that happened.
    """

    __tablename__ = "application_status_events"
    __table_args__ = (
        # The history of one application, in order — the read behind every
        # tracker detail view. Also the pair the repository appends against.
        Index(
            "ix_application_status_events_application_sequence",
            "tracked_application_id",
            "sequence",
        ),
        # "Which applications ever reached this status, and when?" — the funnel
        # questions scan by status and date rather than by application.
        Index(
            "ix_application_status_events_status_changed_at",
            "status",
            "changed_at",
        ),
    )

    tracked_application_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    #: This entry's 0-based position in the application's history. Part of the
    #: primary key, which is what makes appending the same entry twice a
    #: constraint violation rather than a duplicated step.
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(
        String(32),
        comment=(
            "The status moved to: applied | interviewing | offer | rejected | "
            "withdrawn. Never 'draft'. See "
            "src/domain/value_objects/application_status.py."
        ),
    )
    #: The status moved *from* — NULL for `sequence` 0 only, which records the
    #: application being sent. Redundant with the previous row's `status` by
    #: design: it makes one row self-describing ("rejected after interviewing")
    #: and makes a corrupt history detectable rather than merely wrong.
    previous_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment=(
            "The status moved from; NULL only for sequence 0, the entry "
            "recorded when the application was sent."
        ),
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: SENSITIVE. Free text the candidate wrote about this change.
    #:
    #: Encrypted as of migration 0023. It was previously in the clear on the
    #: reading that a note about a job search is "not sensitive the way a
    #: document is" — but the hardening pass could find no principle separating
    #: it from `application_reviews.submission_note` and
    #: `portal_handoffs.resolution_note`, which are the same thing (a note the
    #: candidate typed, unconstrained in content) and were both encrypted. Three
    #: free-text note columns with two answers was an inconsistency, not a
    #: distinction. The examples in `ApplicationStatusChange` settle it:
    #: "referred by Dana" names a third party who never consented to being in
    #: this database at all.
    note: Mapped[str] = mapped_column(
        EncryptedString("application_status_events.note"),
        default="",
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )


class ApplicationReviewModel(Base):
    """One filled application under review by the candidate, and the record of
    them submitting it — see `ApplicationReview`.

    Stored because reviewing an application is not a single-sitting job: the
    candidate reads the answers, goes to check what their visa is actually
    called, comes back, and finishes later. A review that lived only in a
    response would lose every decision they had already made, starting with the
    sensitive ones they had confirmed.

    The partial unique index allows at most one review *in progress* per
    candidate and posting. Two would mean two sets of answers for one
    application and nothing to say which the candidate meant. Submitted rows are
    exempt: a posting applied to twice is two real events, each keeping its own
    answers and timestamps. (Partial indexes are a Postgres feature; on a
    backend that ignores the `WHERE` clause this would become "one review per
    posting, ever", which would reject the second application — this store is
    Postgres.)

    `ON DELETE CASCADE` on the posting, matching `portal_handoffs` rather than
    `application_documents`: a review is the working surface for an application
    in flight, not the archived record of what was sent. The documents that went
    with it are what survive a posting being pruned, and they have their own
    table with RESTRICT.

    SENSITIVE: `answers` is what goes onto a real application — name, email,
    address, and the work-authorization declarations — and `submission_note` is
    the candidate's own free text. Never log either; log `id`, `status`, and
    counts.
    """

    __tablename__ = "application_reviews"
    __table_args__ = (
        Index(
            "uq_application_reviews_open_per_job",
            "user_id",
            "job_posting_id",
            unique=True,
            postgresql_where=text("status = 'in_review'"),
        ),
        # "What have I reviewed and sent?", newest first.
        Index("ix_application_reviews_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    job_posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    #: The apply URL the fill pass ended on — where the candidate goes to send
    #: the application.
    apply_url: Mapped[str] = mapped_column(Text)
    ats_provider: Mapped[str] = mapped_column(
        String(32),
        comment=(
            "Which supported ATS platform the form was read as: greenhouse | "
            "lever | ashby. See src/domain/value_objects/ats_provider.py."
        ),
    )
    status: Mapped[str] = mapped_column(
        String(32),
        comment=(
            "Review lifecycle: in_review | submitted_by_user. Only a "
            "candidate's own action reaches the second. See "
            "src/domain/value_objects/review_status.py."
        ),
    )
    #: Every question the form presented, in page order, as
    #: `[{"key", "label", "widget_kind", "value", "slot", "sensitivity",
    #: "required", "origin", "decided_by_candidate", "explanation"}]`.
    answers: Mapped[list[dict[str, object]]] = mapped_column(
        EncryptedJson("application_reviews.answers"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=(
            "SENSITIVE: AES-256-GCM encrypted at rest (Epic 07) — the answers "
            "on a real application, plus their provenance and the candidate's "
            "decisions. See src/domain/value_objects/reviewed_answer.py."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: Whether the fill pass captured a screenshot. The image is not stored —
    #: it is proof for the session that produced it.
    screenshot_captured: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The Python-side default is what writes the empty note; the column's old
    # `server_default=''` was dropped in migration 0021, because a server-side
    # default on an encrypted column inserts plaintext that nothing can decrypt.
    submission_note: Mapped[str] = mapped_column(
        EncryptedString("application_reviews.submission_note"),
        default="",
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )


class PortalHandoffModel(Base):
    """One application portal where automation stopped at a hard boundary and
    handed control to the candidate — see `PortalHandoff`.

    This row is what makes the pause resumable. The candidate leaves to solve
    a CAPTCHA, sign a form, or log in somewhere else entirely; without a
    stored hand-off they would come back to a reloaded page with no idea what
    they were in the middle of, and nothing downstream could tell a portal
    that is waiting on a human from one nobody has looked at.

    The partial unique index is the important constraint here: at most one
    *open* hand-off per (candidate, posting). Two concurrent inspections of
    the same portal would otherwise each open one and the candidate would be
    asked to do the same thing twice. Resolved rows are exempt, because a
    portal that puts up a wall, gets resolved, and puts up another one is a
    sequence of real events and each one keeps its own evidence and timestamps.
    (Partial indexes are a Postgres feature. On a backend that ignores the
    `WHERE` clause the constraint becomes "one hand-off per posting, ever",
    which would reject that second event — this store is Postgres.)

    The foreign key is `ON DELETE CASCADE`, unlike `application_documents`'
    RESTRICT, and the difference is deliberate: a document snapshot records
    what was sent to an employer and must outlive the posting, while a
    hand-off is an in-flight interaction with a portal. Once the posting is
    gone there is no application to resume, so the row's whole purpose has
    already expired.

    SENSITIVE: `resolution_note` is free text the candidate wrote about how
    they handled the boundary, which can carry anything they thought was
    relevant — an address they registered with, a reference number, a reason.
    Never log it; log `id` and `status`. The `hard_stops` evidence is the
    opposite: it describes the portal's own page and carries nothing about the
    candidate, so it is safe to log and display.
    """

    __tablename__ = "portal_handoffs"
    __table_args__ = (
        Index(
            "uq_portal_handoffs_open_per_job",
            "user_id",
            "job_posting_id",
            unique=True,
            postgresql_where=text("status = 'awaiting_user'"),
        ),
        # "What is waiting on me?", newest first — the panel's only query.
        Index("ix_portal_handoffs_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    job_posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    #: The apply URL automation was asked to work on.
    apply_url: Mapped[str] = mapped_column(Text)
    #: Where it actually stopped — frequently a redirect target, and the URL
    #: the candidate is pointed at to finish the step.
    paused_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32),
        comment=(
            "Hand-off lifecycle: awaiting_user | resumed | abandoned. "
            "See src/domain/value_objects/handoff_status.py."
        ),
    )
    #: The boundaries found, as `[{"kind": ..., "evidence": [...]}]`. JSON
    #: because a page can present more than one at once (a login wall *and* a
    #: CAPTCHA), and because the evidence is a list of lines whose only reader
    #: is the candidate.
    hard_stops: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        comment=(
            "Detected hard boundaries: kind + evidence lines about the "
            "portal's page. See src/domain/value_objects/hard_stop.py."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: When the boundary was last seen. Equal to `created_at` until an
    #: inspection re-reads the same unresolved hand-off.
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # `server_default=''` dropped in migration 0021 — see
    # `ApplicationReviewModel.submission_note` for why.
    resolution_note: Mapped[str] = mapped_column(
        EncryptedString("portal_handoffs.resolution_note"),
        default="",
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )


class WorkHistoryModel(Base):
    __tablename__ = "work_history_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    company_name: Mapped[str] = mapped_column(String(255))
    job_title: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)

    profile: Mapped[UserProfileModel] = relationship(back_populates="work_history")


class EducationModel(Base):
    __tablename__ = "education_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    institution_name: Mapped[str] = mapped_column(String(255))
    degree: Mapped[str] = mapped_column(String(255))
    field_of_study: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)

    profile: Mapped[UserProfileModel] = relationship(back_populates="education")


class SkillModel(Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("profile_id", "name", name="uq_skills_profile_id_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    proficiency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    years_of_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)

    profile: Mapped[UserProfileModel] = relationship(back_populates="skills")


class WorkAuthorizationModel(Base):
    """A profile's work-authorization/citizenship data.

    Kept in its own one-to-one table (`profile_id` is both primary key and
    foreign key) rather than columns on `user_profiles`, so encryption-at-rest
    and restricted access apply to this table without touching the general
    profile row. Every column is flagged sensitive via both `info=`
    (machine-readable) and `comment=` (visible in `\\d` / migrations) — mirrors
    `WorkAuthorization.SENSITIVE` in the domain layer — and every one of them
    is encrypted (Epic 07).

    `status` was a `String(32)` holding a `WorkAuthorizationStatus` value and
    `requires_sponsorship` was a real `Boolean`; both are now encrypted text.
    The enum member and the boolean are still enforced on the Python side (by
    `EncryptedBoolean` here and by `WorkAuthorization` in the domain), but the
    database no longer constrains or aggregates them. Losing "how many
    candidates need sponsorship?" as a SQL question is the intended trade:
    that query is a report on exactly the data this table exists to protect.
    """

    __tablename__ = "work_authorizations"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        EncryptedString("work_authorizations.status"),
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    citizenship_country: Mapped[str | None] = mapped_column(
        EncryptedString("work_authorizations.citizenship_country"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    visa_type: Mapped[str | None] = mapped_column(
        EncryptedString("work_authorizations.visa_type"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    requires_sponsorship: Mapped[bool | None] = mapped_column(
        EncryptedBoolean("work_authorizations.requires_sponsorship"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    details: Mapped[str | None] = mapped_column(
        EncryptedString("work_authorizations.details"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    # Provenance metadata, not itself sensitive PII — no _SENSITIVE_* tags.
    source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)

    profile: Mapped[UserProfileModel] = relationship(
        back_populates="work_authorization"
    )


class EeoSelfIdentificationModel(Base):
    """A profile's voluntary EEO self-identification data.

    Optional one-to-one table, same rationale as `WorkAuthorizationModel`:
    isolated so encryption and access control apply to it alone, every column
    flagged sensitive and every column encrypted (Epic 07). The absence of a
    row for a profile means "not provided" — there is no code path that creates
    one except an explicit candidate submission (see
    `UserProfile.set_eeo_self_identification`).

    A NULL column here still means "this category was left unanswered", and it
    stays a real NULL rather than encrypted emptiness (see
    `_EncryptedColumn`) — so what remains visible at rest is which categories
    were answered, never what the answers were. That is the right side of the
    trade for this table: `DECLINE_TO_SELF_IDENTIFY` is itself one of the
    answers, so "answered" and "declined" are both ciphertext and only
    "skipped" is NULL.
    """

    __tablename__ = "eeo_self_identifications"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    gender_identity: Mapped[str | None] = mapped_column(
        EncryptedString("eeo_self_identifications.gender_identity"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    race_ethnicity: Mapped[str | None] = mapped_column(
        EncryptedString("eeo_self_identifications.race_ethnicity"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    veteran_status: Mapped[str | None] = mapped_column(
        EncryptedString("eeo_self_identifications.veteran_status"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    disability_status: Mapped[str | None] = mapped_column(
        EncryptedString("eeo_self_identifications.disability_status"),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    # Provenance metadata, not itself sensitive PII — no _SENSITIVE_* tags.
    source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)

    profile: Mapped[UserProfileModel] = relationship(
        back_populates="eeo_self_identification"
    )


class ConsentDecisionModel(Base):
    """One recorded consent decision — see `ConsentDecision`.

    Append-only, and the one table in this schema that deliberately survives an
    erasure request. GDPR Art. 7(1) requires this application to be able to
    demonstrate that consent was given, and the entry that matters most after an
    erasure is the withdrawal that triggered it: deleting the ledger destroys the
    evidence that the erasure itself was lawful. See the `consents` category in
    `src/domain/services/personal_data_inventory.py`, which is where that
    decision is declared and where the multi-user follow-up (digest the subject
    id so the retained ledger stops being linkable) is written down.

    Keyed by (`user_id`, `purpose`, `sequence`) with no surrogate id, mirroring
    `ApplicationStatusEventModel`: a decision has no identity of its own beyond
    the ledger it belongs to and its position in it. `sequence` is 0-based and
    gap-free, so the primary key doubles as the ordering — two decisions recorded
    in the same clock tick still have a definite order, which `decided_at` alone
    could not give them. It is also what makes appending the same entry twice a
    constraint violation rather than a duplicated row.

    No foreign key to `user_profiles`: a consent decision is about the account,
    not the profile, and it has to be recordable before a profile exists (the
    first thing a new user does is accept a notice) and to remain readable after
    the profile is erased — which is the whole point of the table.

    Not sensitive, and this is load-bearing rather than incidental. A purpose, a
    yes/no, a timestamp and a notice version describe a *decision about* personal
    data without containing any, which is what lets these columns stay
    unencrypted, queryable, and safe to log — and what makes retaining them past
    an erasure a defensible thing to do rather than a hole in it.
    """

    __tablename__ = "consent_decisions"
    __table_args__ = (
        # The read behind every consent screen and every export: one user's
        # whole ledger, in order. The primary key already serves the
        # per-purpose read.
        Index(
            "ix_consent_decisions_user_id_decided_at",
            "user_id",
            "decided_at",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment=(
            "What was decided about: account_and_applications | "
            "ai_document_generation | answer_reuse | "
            "sensitive_attribute_storage | automated_portal_interaction. See "
            "src/domain/value_objects/consent_purpose.py."
        ),
    )
    #: This decision's 0-based position in the ledger for (user, purpose).
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: True for a grant, False for a withdrawal. A withdrawal is only storable
    #: for a purpose whose lawful basis is consent — enforced by
    #: `ConsentDecision`, not by the schema, because the basis lives in the
    #: domain rather than in a column here.
    granted: Mapped[bool] = mapped_column(Boolean)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: The privacy-notice version the decision was made against. Required:
    #: consent is only valid for what the user was actually told, so this is
    #: what makes "who has to be re-asked after the notice changed?" a query
    #: rather than a guess.
    policy_version: Mapped[str] = mapped_column(
        String(32),
        comment=(
            "The privacy-notice version this decision was made against — what "
            "makes the consent demonstrably informed (GDPR Art. 7(1))."
        ),
    )


class JobMatchFeedbackModel(Base):
    """A candidate's thumbs-up/down reaction to one ranked job match,
    tagged with the score they saw. Append-only — see
    `JobMatchFeedback`'s docstring for why reactions are never updated,
    only inserted.
    """

    __tablename__ = "job_match_feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    job_posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[str] = mapped_column(String(16))
    score_at_feedback: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
