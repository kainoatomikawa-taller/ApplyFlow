"""DTOs — input/output contracts for the ranked-matched-jobs use case."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.application.dtos.job_posting_dtos import JobPostingOutput


@dataclass(frozen=True)
class RankMatchedJobsInput:
    """`as_of` is supplied by the caller (rather than read from the clock
    inside the use case) so a run is deterministic and testable — same
    convention as `DetectStaleJobPostingsInput`/`GenerateJobFitRationaleInput`."""

    user_id: str
    as_of: date
    limit: int = 100


@dataclass(frozen=True)
class RankedJobOutput:
    """One entry in the final ranked list: a job the candidate is not
    hard-disqualified from, with its fit score, "why this fits"
    rationale, and gap list of unmet soft preferences."""

    job_posting: JobPostingOutput
    score: int
    rationale: str
    gaps: list[str] = field(default_factory=list)
