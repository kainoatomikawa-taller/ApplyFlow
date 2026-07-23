"""SQLAlchemy ORM models.

ORM models live in infrastructure and MUST NOT leak into domain or
application. Mapping to/from domain entities happens in the repository.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
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


class UserProfileModel(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Contact info — postal address. Not sensitive-flagged.
    street_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state_or_region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Links — portfolio/LinkedIn/GitHub. Not sensitive-flagged.
    portfolio_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

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

    profile: Mapped[UserProfileModel] = relationship(
        back_populates="eeo_self_identification"
    )
