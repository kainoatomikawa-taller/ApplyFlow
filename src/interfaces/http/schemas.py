"""Pydantic request/response schemas.

These are presentation-layer contracts. Input validation (shape, types)
happens here; business rules are enforced in the domain layer.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class CreateApplicationRequest(BaseModel):
    candidate_email: EmailStr
    company_name: str = Field(min_length=1, max_length=255)
    role_title: str = Field(min_length=1, max_length=255)
    job_description: str = Field(min_length=1)


class AnalyzeApplicationRequest(BaseModel):
    resume_text: str = Field(min_length=1)


class ApplicationResponse(BaseModel):
    id: str
    candidate_email: str
    company_name: str
    role_title: str
    status: str
    match_score: int | None
    tailored_cover_letter: str | None
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    message: str


class ResumeResponse(BaseModel):
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    extracted_text: str
    created_at: datetime


class WorkHistoryResponse(BaseModel):
    id: str
    company_name: str
    job_title: str
    start_date: date
    end_date: date | None
    location: str | None
    description: str | None
    source: str


class EducationResponse(BaseModel):
    id: str
    institution_name: str
    degree: str
    field_of_study: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    source: str


class SkillResponse(BaseModel):
    id: str
    name: str
    proficiency: str | None
    years_of_experience: int | None
    source: str


class ProfileResponse(BaseModel):
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
    work_history: list[WorkHistoryResponse]
    education: list[EducationResponse]
    skills: list[SkillResponse]


class JobRequirementsResponse(BaseModel):
    degree_level: str | None
    degree_required: bool | None
    clearance_level: str | None
    clearance_required: bool | None
    remote_type: str | None
    work_authorization: str | None
    min_years_experience: int | None
    max_years_experience: int | None
    locations: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    preferences: list[str]


class JobPostingResponse(BaseModel):
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
    requirements: JobRequirementsResponse | None = None


class RankedJobResponse(BaseModel):
    job_posting: JobPostingResponse
    score: int
    rationale: str
    gaps: list[str]
