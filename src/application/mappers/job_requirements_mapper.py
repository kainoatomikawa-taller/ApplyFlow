"""Mapper between the JobRequirements value object and its output DTO."""

from __future__ import annotations

from src.application.dtos.job_requirements_dtos import JobRequirementsOutput
from src.domain.value_objects.job_requirements import JobRequirements


class JobRequirementsMapper:
    """Translates the domain value object into an output DTO."""

    @staticmethod
    def to_output(requirements: JobRequirements) -> JobRequirementsOutput:
        return JobRequirementsOutput(
            degree_level=(
                requirements.degree_level.value if requirements.degree_level else None
            ),
            degree_required=requirements.degree_required,
            clearance_level=(
                requirements.clearance_level.value
                if requirements.clearance_level
                else None
            ),
            clearance_required=requirements.clearance_required,
            remote_type=(
                requirements.remote_type.value if requirements.remote_type else None
            ),
            work_authorization=(
                requirements.work_authorization.value
                if requirements.work_authorization
                else None
            ),
            min_years_experience=requirements.min_years_experience,
            max_years_experience=requirements.max_years_experience,
            locations=list(requirements.locations),
            required_skills=list(requirements.required_skills),
            preferred_skills=list(requirements.preferred_skills),
            preferences=list(requirements.preferences),
            employment_type=(
                requirements.employment_type.value
                if requirements.employment_type
                else None
            ),
            hiring_term=(
                requirements.hiring_term.label if requirements.hiring_term else None
            ),
            job_function=(
                requirements.job_function.value if requirements.job_function else None
            ),
            student_status_requirement=(
                requirements.student_status_requirement.value
                if requirements.student_status_requirement
                else None
            ),
        )
