"""JobMatchFeedbackRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation
lives in infrastructure/. The domain and application layers depend only
on this abstraction, never on a specific database.

Tuning-signal contract: `list_all` is the bulk read path a future
scoring-tuning pass consumes — it groups the returned feedback by
`score_at_feedback` into bands and computes each band's real
thumbs-up/thumbs-down agreement rate (see `ScoringFeedbackAnalyzer`, the
first consumer of this data, and `AnalyzeScoringFeedback`, the use case
that exposes it). A band whose agreement rate diverges sharply from what
its score implies — e.g. 80-100-scored matches getting mostly
thumbs-down — is the concrete signal that `SoftPreferenceEvaluator`'s
scoring weights need revisiting. Actually recalibrating those weights
from the signal is future work; this repository's `list_all` (plus
`ScoringFeedbackAnalyzer`) is the read path and first analysis step it
will be built on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.job_match_feedback import JobMatchFeedback


class JobMatchFeedbackRepository(ABC):
    """Persistence contract for `JobMatchFeedback` records."""

    @abstractmethod
    async def add(self, feedback: JobMatchFeedback) -> None:
        """Persist a new feedback reaction. Feedback is append-only —
        this never updates an existing record."""

    @abstractmethod
    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedback]:
        """Return a candidate's own feedback history, newest first."""

    @abstractmethod
    async def list_by_job_posting_id(
        self, job_posting_id: str, *, limit: int = 100
    ) -> list[JobMatchFeedback]:
        """Return every reaction recorded against one job posting, newest
        first."""

    @abstractmethod
    async def list_all(self, *, limit: int = 1000) -> list[JobMatchFeedback]:
        """Return feedback across every user and job, newest first — the
        bulk read path for tuning analysis (see module docstring)."""
