"""AnalyzeScoringFeedback use case — the queryable tuning-analysis path:
reads feedback across every user/job and buckets it by score into an
agreement-rate summary. See `ScoringFeedbackAnalyzer` and
`JobMatchFeedbackRepository` for the full tuning-signal contract this
feeds into.
"""

from __future__ import annotations

from src.application.dtos.job_match_feedback_dtos import ScoringFeedbackSummaryOutput
from src.application.mappers.job_match_feedback_mapper import JobMatchFeedbackMapper
from src.domain.repositories.job_match_feedback_repository import (
    JobMatchFeedbackRepository,
)
from src.domain.services.scoring_feedback_analyzer import ScoringFeedbackAnalyzer


class AnalyzeScoringFeedback:
    def __init__(
        self,
        repository: JobMatchFeedbackRepository,
        analyzer: ScoringFeedbackAnalyzer | None = None,
    ) -> None:
        self._repository = repository
        self._analyzer = analyzer or ScoringFeedbackAnalyzer()

    async def execute(self, *, limit: int = 1000) -> ScoringFeedbackSummaryOutput:
        feedback = await self._repository.list_all(limit=limit)
        buckets = self._analyzer.analyze(feedback)
        return ScoringFeedbackSummaryOutput(
            buckets=[JobMatchFeedbackMapper.to_bucket_output(b) for b in buckets]
        )
