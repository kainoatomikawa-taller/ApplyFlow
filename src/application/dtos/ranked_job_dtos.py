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
    #: Whether to keep roles the candidate has already applied to. Off by
    #: default: the ranked list is a list of things to apply to, and a job
    #: already applied for is not one of them. A caller that wants the full
    #: picture (a "you already applied" section, an audit of what was
    #: suppressed) turns this on and reads `RankedJobOutput.already_applied`
    #: — the flag is set either way, so the two modes cannot disagree about
    #: which entries are re-applications.
    include_already_applied: bool = False


@dataclass(frozen=True)
class RankedJobOutput:
    """One entry in the final ranked list: a job the candidate is not
    hard-disqualified from, with its fit score, "why this fits"
    rationale, and gap list of unmet soft preferences."""

    job_posting: JobPostingOutput
    score: int
    rationale: str
    gaps: list[str] = field(default_factory=list)
    #: Whether the candidate has already applied to this role — matched on
    #: canonical identity (company + title + location), not posting id, so a
    #: relisted or re-ingested posting is still flagged. Only ever `True` for
    #: entries returned under `include_already_applied`; otherwise these
    #: entries are suppressed before they reach the list.
    already_applied: bool = False
