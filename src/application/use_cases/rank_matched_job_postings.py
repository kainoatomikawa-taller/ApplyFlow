"""RankMatchedJobPostings use case — assembles the final ranked job list:
filtered for hard disqualifiers, ordered by fit score, each entry
carrying its score, rationale, and gap list.

This is the culmination of the matching pipeline built by earlier tasks:
`HardDisqualifierFilter` does the filtering, `SoftPreferenceEvaluator`
supplies both the fit score and the gap list, and
`JobFitRationaleGeneratorPort` writes the "why this fits" narrative — all
composed directly here (never through another use case, per the "use
cases never depend on each other" rule) so one bulk ranking run loads the
profile and active postings exactly once rather than re-fetching per job.

A single posting's rationale-generation failure never drops it from the
list — that would silently hide a job the candidate genuinely qualifies
for over a transient LLM hiccup — it falls back to a plain, deterministic
summary of the same facts the LLM would have been given instead.

Roles the candidate has already applied to are dropped before any of
that. The tracker's records feed back in here as an `AppliedJobIndex`,
matched on canonical identity (company + title + location — see
`CanonicalJobIdentity`) rather than posting id, so a role that was
re-ingested, relisted, or picked up from a second aggregator is still
recognized as one the candidate has sent an application to. The test runs
*before* the rationale call for a second reason beyond the nudge: a
suppressed job is one fewer LLM request per ranking run.
"""

from __future__ import annotations

from datetime import date

from src.application.dtos.ranked_job_dtos import RankedJobOutput, RankMatchedJobsInput
from src.application.exceptions import ExternalServiceError
from src.application.mappers.job_posting_mapper import JobPostingMapper
from src.application.ports.job_fit_rationale_generator_port import (
    JobFitRationaleGeneratorPort,
)
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)
from src.domain.services.applied_job_index import AppliedJobIndex
from src.domain.services.hard_disqualifier_filter import HardDisqualifierFilter
from src.domain.services.requirement_classifier import RequirementClassifier
from src.domain.services.soft_preference_evaluator import SoftPreferenceEvaluator
from src.domain.value_objects.job_requirements import JobRequirements


class RankMatchedJobPostings:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        profile_repository: ProfileRepository,
        rationale_generator: JobFitRationaleGeneratorPort,
        tracked_application_repository: TrackedApplicationRepository,
        disqualifier_filter: HardDisqualifierFilter | None = None,
        classifier: RequirementClassifier | None = None,
        soft_evaluator: SoftPreferenceEvaluator | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._profile_repository = profile_repository
        self._rationale_generator = rationale_generator
        self._tracked_application_repository = tracked_application_repository
        self._disqualifier_filter = disqualifier_filter or HardDisqualifierFilter()
        self._classifier = classifier or RequirementClassifier()
        self._soft_evaluator = soft_evaluator or SoftPreferenceEvaluator()

    async def execute(self, dto: RankMatchedJobsInput) -> list[RankedJobOutput]:
        profile = await self._profile_repository.get_by_user_id(dto.user_id)
        if profile is None:
            raise ProfileNotFoundError(dto.user_id)

        postings = await self._job_posting_repository.list_active(limit=dto.limit)
        # Loaded once for the whole run: the candidate's applied-to set does
        # not change while a ranking is being assembled, and asking per
        # posting would be a round trip per job.
        applied = AppliedJobIndex(
            await self._tracked_application_repository.list_applied_identities(
                user_id=dto.user_id
            )
        )

        ranked: list[RankedJobOutput] = []
        for posting in postings:
            requirements = posting.requirements or JobRequirements()
            if not self._disqualifier_filter.evaluate(profile, requirements).qualifies:
                continue
            already_applied = applied.has_applied_to(posting)
            if already_applied and not dto.include_already_applied:
                continue
            ranked.append(
                await self._rank_one(
                    posting,
                    profile,
                    requirements,
                    as_of=dto.as_of,
                    already_applied=already_applied,
                )
            )

        ranked.sort(key=lambda entry: entry.score, reverse=True)
        return ranked

    async def _rank_one(
        self,
        posting: JobPosting,
        profile: UserProfile,
        requirements: JobRequirements,
        *,
        as_of: date,
        already_applied: bool,
    ) -> RankedJobOutput:
        classification = self._classifier.classify(requirements)
        soft_evaluation = self._soft_evaluator.evaluate(
            profile, requirements, as_of=as_of
        )

        matched = tuple(item.description for item in classification.hard) + tuple(
            item.description for item in soft_evaluation.met
        )
        gaps = tuple(item.description for item in soft_evaluation.gaps)

        try:
            rationale = await self._rationale_generator.generate(
                job_title=posting.title,
                company=posting.company,
                matched=matched,
                gaps=gaps,
            )
        except ExternalServiceError:
            rationale = self._fallback_rationale(matched)

        return RankedJobOutput(
            job_posting=JobPostingMapper.to_output(posting),
            score=soft_evaluation.fit_score,
            rationale=rationale,
            gaps=list(gaps),
            already_applied=already_applied,
        )

    @staticmethod
    def _fallback_rationale(matched: tuple[str, ...]) -> str:
        if not matched:
            return (
                "This role's requirements have not yet been fully assessed "
                "against your profile."
            )
        return "Matches: " + "; ".join(matched) + "."
