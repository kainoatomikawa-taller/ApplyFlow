"""SQLAlchemy ORM models.

ORM models live in infrastructure and MUST NOT leak into domain or
application. Mapping to/from domain entities happens in the repository.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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
