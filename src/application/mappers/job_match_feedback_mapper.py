"""Mapper between JobMatchFeedback/ScoreBucketAgreement and their output DTOs."""

from __future__ import annotations

from src.application.dtos.job_match_feedback_dtos import (
    JobMatchFeedbackOutput,
    ScoreBucketAgreementOutput,
)
from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.services.scoring_feedback_analyzer import ScoreBucketAgreement


class JobMatchFeedbackMapper:
    """Translates domain entities/value objects into output DTOs."""

    @staticmethod
    def to_output(feedback: JobMatchFeedback) -> JobMatchFeedbackOutput:
        return JobMatchFeedbackOutput(
            id=feedback.id,
            user_id=feedback.user_id,
            job_posting_id=feedback.job_posting_id,
            rating=feedback.rating.value,
            score_at_feedback=feedback.score_at_feedback,
            created_at=feedback.created_at,
        )

    @staticmethod
    def to_bucket_output(bucket: ScoreBucketAgreement) -> ScoreBucketAgreementOutput:
        return ScoreBucketAgreementOutput(
            range_start=bucket.range_start,
            range_end=bucket.range_end,
            thumbs_up=bucket.thumbs_up,
            thumbs_down=bucket.thumbs_down,
            agreement_rate=bucket.agreement_rate,
        )
