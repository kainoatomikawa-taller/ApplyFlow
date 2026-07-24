"""DetectJobRequirementGaps use case — checks a job posting's parsed
requirements against a candidate's profile facts and remembered answers,
flagging every requirement neither source backs up as a gap.

Unlike `SoftPreferenceEvaluator` (which only ever flags a *soft*
preference the profile affirmatively fails, treating silence as neutral so
fit scoring is never unfairly punitive), this use case checks every
requirement — hard and soft alike — and treats an unbacked requirement as
a gap even when nothing contradicts it. The two coexist deliberately:
`SoftPreferenceEvaluator` answers "does this disqualify or hurt the fit
score", this answers "what should the candidate know they haven't
established yet" — a strictly more complete, informational gap list, not
a ranking input.

Both the candidate's facts and the requirement descriptions are assembled
from real data before the LLM ever sees them (`CandidateFactExtractor` for
the profile, raw Q&A text for `AnswerMemory`, `RequirementClassifier` for
the requirements) — the LLM's only job is to judge which requirements
those facts back up, never to invent a fact or a requirement of its own.
"""

from __future__ import annotations

from src.application.dtos.requirement_gap_dtos import (
    DetectJobRequirementGapsInput,
    JobRequirementGapsOutput,
)
from src.application.ports.requirement_gap_detector_port import (
    RequirementGapDetectorPort,
)
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.services.candidate_fact_extractor import CandidateFactExtractor
from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.value_objects.job_requirements import JobRequirements


class DetectJobRequirementGaps:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        profile_repository: ProfileRepository,
        answer_memory_repository: AnswerMemoryRepository,
        detector: RequirementGapDetectorPort,
        classifier: RequirementClassifier | None = None,
        fact_extractor: CandidateFactExtractor | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._profile_repository = profile_repository
        self._answer_memory_repository = answer_memory_repository
        self._detector = detector
        self._classifier = classifier or RequirementClassifier()
        self._fact_extractor = fact_extractor or CandidateFactExtractor()

    async def execute(
        self, dto: DetectJobRequirementGapsInput
    ) -> JobRequirementGapsOutput:
        posting = await self._job_posting_repository.get_by_id(dto.job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        profile = await self._profile_repository.get_by_user_id(dto.user_id)
        if profile is None:
            raise ProfileNotFoundError(dto.user_id)

        answer_memories = await self._answer_memory_repository.list_by_user_id(
            dto.user_id
        )

        requirements = posting.requirements or JobRequirements()
        classification = self._classifier.classify(requirements)
        requirement_descriptions = tuple(
            item.description for item in (*classification.hard, *classification.soft)
        )

        candidate_facts = self._fact_extractor.extract(
            profile, as_of=dto.as_of
        ) + tuple(
            f"Q: {memory.question_text} A: {memory.answer_text}"
            for memory in answer_memories
        )

        gaps = await self._detector.detect_gaps(
            job_title=posting.title,
            company=posting.company,
            requirements=requirement_descriptions,
            candidate_facts=candidate_facts,
        )

        return JobRequirementGapsOutput(job_posting_id=posting.id, gaps=list(gaps))
