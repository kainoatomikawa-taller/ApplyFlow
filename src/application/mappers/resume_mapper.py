"""Mapper between the Resume entity and its output DTO."""

from __future__ import annotations

from src.application.dtos.resume_dtos import ResumeOutput
from src.domain.entities.resume import Resume


class ResumeMapper:
    """Translates domain entities into output DTOs."""

    @staticmethod
    def to_output(resume: Resume) -> ResumeOutput:
        return ResumeOutput(
            id=resume.id,
            original_filename=resume.original_filename,
            content_type=resume.content_type,
            size_bytes=resume.size_bytes,
            extracted_text=resume.extracted_text,
            created_at=resume.created_at,
        )
