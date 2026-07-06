"""DTOs — input/output contracts for the job application use cases.

DTOs are plain data with no behavior. Use cases accept input DTOs and
return output DTOs; they never leak domain entities across the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CreateJobApplicationInput:
    candidate_email: str
    company_name: str
    role_title: str
    job_description: str


@dataclass(frozen=True)
class AnalyzeApplicationInput:
    application_id: str
    resume_text: str


@dataclass(frozen=True)
class JobApplicationOutput:
    id: str
    candidate_email: str
    company_name: str
    role_title: str
    status: str
    match_score: int | None
    tailored_cover_letter: str | None
    created_at: datetime
    updated_at: datetime
