"""GenerateJobFitRationale use case — produces a short, honest "why this
fits" rationale and a gap list of unmet soft preferences for one job
posting against one candidate profile.

Assumes the posting has already cleared hard-disqualifier filtering (see
`HardDisqualifierFilter` / `ListEligibleJobPostings`) — this use case
covers the "scored"/eligible job set downstream of that filter, so a
posting's hard requirements are treated as already met here rather than
re-verified. Only the soft preferences (see `SoftPreferenceEvaluator`) are
newly evaluated, since those are exactly what's still open — met ones
ground the rationale, unmet ones become the gap list.
"""

from __future__ import annotations

from src.application.dtos.job_fit_rationale_dtos import (
    GenerateJobFitRationaleInput,
    JobFitRationaleOutput,
)
from src.application.ports.job_fit_rationale_generator_port import (
    JobFitRationaleGeneratorPort,
)
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.services.soft_preference_evaluator import SoftPreferenceEvaluator
from src.domain.value_objects.job_requirements import JobRequirements


class GenerateJobFitRationale:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        profile_repository: ProfileRepository,
        generator: JobFitRationaleGeneratorPort,
        classifier: RequirementClassifier | None = None,
        soft_evaluator: SoftPreferenceEvaluator | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._profile_repository = profile_repository
        self._generator = generator
        self._classifier = classifier or RequirementClassifier()
        self._soft_evaluator = soft_evaluator or SoftPreferenceEvaluator()

    async def execute(
        self, dto: GenerateJobFitRationaleInput
    ) -> JobFitRationaleOutput:
        posting = await self._job_posting_repository.get_by_id(dto.job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        profile = await self._profile_repository.get_by_id(dto.profile_id)
        if profile is None:
            raise ProfileNotFoundError(dto.profile_id)

        requirements = posting.requirements or JobRequirements()
        classification = self._classifier.classify(requirements)
        soft_evaluation = self._soft_evaluator.evaluate(
            profile, requirements, as_of=dto.as_of
        )

        matched = tuple(item.description for item in classification.hard) + tuple(
            item.description for item in soft_evaluation.met
        )
        gaps = tuple(item.description for item in soft_evaluation.gaps)

        rationale = await self._generator.generate(
            job_title=posting.title,
            company=posting.company,
            matched=matched,
            gaps=gaps,
        )

        return JobFitRationaleOutput(
            job_posting_id=posting.id, rationale=rationale, gaps=list(gaps)
        )
