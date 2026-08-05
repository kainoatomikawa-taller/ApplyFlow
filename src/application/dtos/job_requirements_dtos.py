"""DTOs — input/output contracts for the job-requirements extraction use
case. DTOs are plain data with no behavior; output DTOs flatten domain
enums to their string values so use cases never leak domain types across
the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExtractJobRequirementsInput:
    job_posting_id: str


@dataclass(frozen=True)
class JobRequirementsOutput:
    degree_level: str | None
    degree_required: bool | None
    clearance_level: str | None
    clearance_required: bool | None
    remote_type: str | None
    work_authorization: str | None
    min_years_experience: int | None
    max_years_experience: int | None
    locations: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    # What the posting *is*, rather than what it demands of the candidate.
    # Defaulted and placed last so the existing constructions of this DTO did not
    # all have to change when employment type, term and function were added.
    employment_type: str | None = None
    #: "Summer 2027", or "Summer" when the year is unstated. A rendered label
    #: rather than season/year parts: every consumer so far wants to display it,
    #: and the domain is the one place that should decide the wording.
    hiring_term: str | None = None
    job_function: str | None = None
    student_status_requirement: str | None = None


@dataclass(frozen=True)
class ExtractJobRequirementsOutput:
    job_posting_id: str
    requirements: JobRequirementsOutput
