"""DTOs — input/output contracts for the resume use cases.

DTOs are plain data with no behavior. Use cases accept input DTOs and
return output DTOs; they never leak domain entities across the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UploadResumeInput:
    user_id: str
    original_filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class ResumeOutput:
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    extracted_text: str
    created_at: datetime
