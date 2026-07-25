"""SQLAlchemy ORM models.

ORM models live in infrastructure and MUST NOT leak into domain or
application. Mapping to/from domain entities happens in the repository.
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

# Mirrors the `SENSITIVE = True` flag on the domain value objects
# (`WorkAuthorization`, `EeoSelfIdentification`) at the schema level, so
# Epic 07 can find every column requiring encryption-at-rest/restricted
# access without re-deriving the list from application code.
_SENSITIVE_COLUMN_INFO = {"sensitive": True}
_SENSITIVE_COMMENT = "SENSITIVE: encrypt at rest / restrict access (Epic 07)."

# Every stored fact carries a provenance tag mirroring the domain's
# `ProvenanceSource` — see that module for the full Epic 04 contract.
# `String(16)` comfortably fits the longest member ("parsed_resume").
_PROVENANCE_COMMENT = (
    "Fact provenance: parsed_resume | user_entered | answer. "
    "Required — see src/domain/value_objects/provenance_source.py."
)


class JobApplicationModel(Base):
    __tablename__ = "job_applications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_email: Mapped[str] = mapped_column(String(320), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    role_title: Mapped[str] = mapped_column(String(255))
    job_description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tailored_cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    requirements: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )


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
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    # Provenance for full_name/email/phone/headline/location as a bundle —
    # see UserProfile's module docstring for why. Always required: those
    # fields are always present once a profile exists.
    contact_source: Mapped[str] = mapped_column(
        String(16), comment=_PROVENANCE_COMMENT
    )
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Contact info — postal address. Not sensitive-flagged.
    street_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state_or_region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Nullable: only required once the address above actually has data —
    # enforced by UserProfile._validate_optional_source, not by the schema.
    address_source: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment=_PROVENANCE_COMMENT
    )

    # Links — portfolio/LinkedIn/GitHub. Not sensitive-flagged.
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
    and the file on disk. `original_filename` and `extracted_text` may
    contain PII, so never log them; log the row's `id` instead.
    """

    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str] = mapped_column(
        String(255), comment="May contain PII — never log."
    )
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    extracted_text: Mapped[str] = mapped_column(
        Text, comment="May contain PII — never log."
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
        Text, info=_SENSITIVE_COLUMN_INFO, comment=_SENSITIVE_COMMENT
    )
    answer_text: Mapped[str] = mapped_column(
        Text, info=_SENSITIVE_COLUMN_INFO, comment=_SENSITIVE_COMMENT
    )
    # A plain JSON array of floats rather than a pgvector column: this
    # ticket only covers storage, not similarity search, and pgvector
    # isn't a dependency yet — a future retrieval epic can migrate this
    # column once it needs indexed nearest-neighbor queries.
    embedding: Mapped[list[float]] = mapped_column(
        JSON, info=_SENSITIVE_COLUMN_INFO, comment=_SENSITIVE_COMMENT
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
        Text, info=_SENSITIVE_COLUMN_INFO, comment=_SENSITIVE_COMMENT
    )
    #: Hex sha256 of `content` — integrity, not identity. Not sensitive: a
    #: digest reveals nothing about the document it describes.
    content_sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    #: The provenance the content traces to, mirroring the domain's
    #: `ProvenanceSource` — a JSON array because a document is normally
    #: backed by several sources at once, unlike a single stored fact.
    backing_sources: Mapped[list[str]] = mapped_column(
        JSON, comment=_PROVENANCE_COMMENT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
    resolution_note: Mapped[str] = mapped_column(
        Text,
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
    foreign key) rather than columns on `user_profiles`, so Epic 07 can
    apply encryption-at-rest and restricted access to this table without
    touching the general profile row. Every column is flagged sensitive via
    both `info=` (machine-readable) and `comment=` (visible in `\\d` /
    migrations) — mirrors `WorkAuthorization.SENSITIVE` in the domain layer.
    """

    __tablename__ = "work_authorizations"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(32), info=_SENSITIVE_COLUMN_INFO, comment=_SENSITIVE_COMMENT
    )
    citizenship_country: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    visa_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    requires_sponsorship: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    details: Mapped[str | None] = mapped_column(
        Text, nullable=True, info=_SENSITIVE_COLUMN_INFO, comment=_SENSITIVE_COMMENT
    )
    # Provenance metadata, not itself sensitive PII — no _SENSITIVE_* tags.
    source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)

    profile: Mapped[UserProfileModel] = relationship(
        back_populates="work_authorization"
    )


class EeoSelfIdentificationModel(Base):
    """A profile's voluntary EEO self-identification data.

    Optional one-to-one table, same rationale as `WorkAuthorizationModel`:
    isolated for Epic 07's encryption/access-control work, every column
    flagged sensitive. The absence of a row for a profile means "not
    provided" — there is no code path that creates one except an explicit
    candidate submission (see `UserProfile.set_eeo_self_identification`).
    """

    __tablename__ = "eeo_self_identifications"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    gender_identity: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    race_ethnicity: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    veteran_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    disability_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        info=_SENSITIVE_COLUMN_INFO,
        comment=_SENSITIVE_COMMENT,
    )
    # Provenance metadata, not itself sensitive PII — no _SENSITIVE_* tags.
    source: Mapped[str] = mapped_column(String(16), comment=_PROVENANCE_COMMENT)

    profile: Mapped[UserProfileModel] = relationship(
        back_populates="eeo_self_identification"
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
