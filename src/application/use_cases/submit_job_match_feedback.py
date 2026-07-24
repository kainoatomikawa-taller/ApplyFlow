"""SubmitJobMatchFeedback use case — records a candidate's thumbs-up/down
reaction to one ranked job match, tagged with the job and the score they
saw when they reacted.

Verifies the job posting exists (feedback tied to a phantom id would be
useless for tuning), then persists an append-only `JobMatchFeedback`
record — see that entity's docstring for why reactions are never
overwritten.
"""

from __future__ import annotations

from src.application.dtos.job_match_feedback_dtos import (
    JobMatchFeedbackOutput,
    SubmitJobMatchFeedbackInput,
)
from src.application.mappers.job_match_feedback_mapper import JobMatchFeedbackMapper
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.job_match_feedback import JobMatchFeedback
from src.domain.exceptions import InvalidValueError, JobPostingNotFoundError
from src.domain.repositories.job_match_feedback_repository import (
    JobMatchFeedbackRepository,
)
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.feedback_rating import FeedbackRating


class SubmitJobMatchFeedback:
    def __init__(
        self,
        feedback_repository: JobMatchFeedbackRepository,
        job_posting_repository: JobPostingRepository,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._feedback_repository = feedback_repository
        self._job_posting_repository = job_posting_repository
        self._id_generator = id_generator

    async def execute(
        self, dto: SubmitJobMatchFeedbackInput
    ) -> JobMatchFeedbackOutput:
        posting = await self._job_posting_repository.get_by_id(dto.job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        try:
            rating = FeedbackRating(dto.rating)
        except ValueError as exc:
            raise InvalidValueError(
                f"'{dto.rating}' is not a valid feedback rating."
            ) from exc

        feedback = JobMatchFeedback(
            id=self._id_generator.new_id(),
            user_id=dto.user_id,
            job_posting_id=dto.job_posting_id,
            rating=rating,
            score_at_feedback=dto.score_at_feedback,
        )
        await self._feedback_repository.add(feedback)

        return JobMatchFeedbackMapper.to_output(feedback)
