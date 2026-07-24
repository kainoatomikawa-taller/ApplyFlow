"""DTOs — output contracts for `UserProfile` use cases.

DTOs are plain data with no behavior. Use cases return these instead of
leaking domain entities (or their value objects/enums) across the
boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class WorkHistoryOutput:
    id: str
    company_name: str
    job_title: str
    start_date: date
    end_date: date | None
    location: str | None
    description: str | None
    source: str


@dataclass(frozen=True)
class EducationOutput:
    id: str
    institution_name: str
    degree: str
    field_of_study: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    source: str


@dataclass(frozen=True)
class SkillOutput:
    id: str
    name: str
    proficiency: str | None
    years_of_experience: int | None
    source: str


@dataclass(frozen=True)
class ProfileOutput:
    id: str
    user_id: str
    full_name: str
    email: str
    contact_source: str
    phone: str | None
    headline: str | None
    location: str | None
    created_at: datetime
    updated_at: datetime
    work_history: list[WorkHistoryOutput] = field(default_factory=list)
    education: list[EducationOutput] = field(default_factory=list)
    skills: list[SkillOutput] = field(default_factory=list)
