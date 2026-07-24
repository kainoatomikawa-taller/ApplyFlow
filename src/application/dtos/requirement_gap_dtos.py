"""DTOs — input/output contracts for the job-requirement-gap-detection use
case."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class DetectJobRequirementGapsInput:
    """`as_of` is supplied by the caller (rather than read from the clock
    inside the use case) so a run is deterministic and testable — same
    convention as `GenerateJobFitRationaleInput`/`RankMatchedJobsInput`."""

    job_posting_id: str
    user_id: str
    as_of: date


@dataclass(frozen=True)
class JobRequirementGapsOutput:
    job_posting_id: str
    gaps: list[str] = field(default_factory=list)
