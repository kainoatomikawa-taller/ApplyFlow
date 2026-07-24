"""DTOs for reading `JobPosting` records — the active job set downstream
matching/browsing reads instead of the raw table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.application.dtos.job_requirements_dtos import JobRequirementsOutput


@dataclass(frozen=True)
class JobPostingOutput:
    id: str
    source: str
    company: str
    title: str
    apply_url: str
    location: str | None
    is_remote: bool
    status: str
    posted_at: date | None
    created_at: datetime
    requirements: JobRequirementsOutput | None = None
