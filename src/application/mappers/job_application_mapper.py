"""Mapper between the JobApplication entity and its output DTO."""

from __future__ import annotations

from src.application.dtos.job_application_dtos import JobApplicationOutput
from src.domain.entities.job_application import JobApplication


class JobApplicationMapper:
    """Translates domain entities into output DTOs."""

    @staticmethod
    def to_output(application: JobApplication) -> JobApplicationOutput:
        return JobApplicationOutput(
            id=application.id,
            candidate_email=str(application.candidate_email),
            company_name=application.company_name,
            role_title=application.role_title,
            status=application.status.value,
            match_score=(
                int(application.match_score)
                if application.match_score is not None
                else None
            ),
            tailored_cover_letter=application.tailored_cover_letter,
            created_at=application.created_at,
            updated_at=application.updated_at,
        )
