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
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResolvedListingModel(Base):
    """A permanent cache entry: the canonical apply URL + description a
    search API resolved for a company whose aggregator listing arrived
    without one or both. `normalized_company` is unique — once a company
    has a row here, `SearchApiListingResolver` never searches it again.
    """

    __tablename__ = "resolved_listings"

    normalized_company: Mapped[str] = mapped_column(String(255), primary_key=True)
    company: Mapped[str] = mapped_column(String(255))
    apply_url: Mapped[str] = mapped_column(String(2048))
    description: Mapped[str] = mapped_column(Text)
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
