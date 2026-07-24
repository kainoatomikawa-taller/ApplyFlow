"""ClassifyJobRequirements use case — loads a job posting's parsed
`JobRequirements` and splits them into hard disqualifiers and soft
preferences via `RequirementClassifier` (a pure domain service).

A posting that hasn't had Epic 03 extraction run yet (`requirements is
None`) has nothing to classify — this is a benign, expected state (not
yet processed), not an error, so it yields an empty classification rather
than raising.
"""

from __future__ import annotations

from src.application.dtos.requirement_classification_dtos import (
    ClassifyJobRequirementsInput,
    RequirementClassificationOutput,
)
from src.application.mappers.requirement_classification_mapper import (
    RequirementClassificationMapper,
)
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.value_objects.job_requirements import JobRequirements


class ClassifyJobRequirements:
    def __init__(
        self,
        repository: JobPostingRepository,
        classifier: RequirementClassifier | None = None,
    ) -> None:
        self._repository = repository
        self._classifier = classifier or RequirementClassifier()

    async def execute(
        self, dto: ClassifyJobRequirementsInput
    ) -> RequirementClassificationOutput:
        job_posting = await self._repository.get_by_id(dto.job_posting_id)
        if job_posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        requirements = job_posting.requirements or JobRequirements()
        classification = self._classifier.classify(requirements)
        return RequirementClassificationMapper.to_output(
            job_posting.id, classification
        )
