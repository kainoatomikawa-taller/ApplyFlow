"""DTOs — input/output contracts for the job-fit-rationale use case."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class GenerateJobFitRationaleInput:
    """`as_of` is supplied by the caller (rather than read from the clock
    inside the use case) so a run is deterministic and testable — same
    convention as `DetectStaleJobPostingsInput`."""

    job_posting_id: str
    profile_id: str
    as_of: date


@dataclass(frozen=True)
class JobFitRationaleOutput:
    job_posting_id: str
    rationale: str
    gaps: list[str] = field(default_factory=list)
