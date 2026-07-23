"""SQLAlchemy ORM models.

ORM models live in infrastructure and MUST NOT leak into domain or
application. Mapping to/from domain entities happens in the repository.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
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
