"""ListEligibleJobPostings use case — the active job set, filtered down
to postings a candidate genuinely qualifies for.

Reads from the same active job set `ListActiveJobPostings` reads from,
then excludes any posting whose hard disqualifiers (see
`HardDisqualifierFilter`) the candidate's profile fails. A posting that
hasn't had Epic 03 requirement extraction run yet has no hard
disqualifiers to fail, so it's always included.
"""

from __future__ import annotations

from src.application.dtos.job_posting_dtos import JobPostingOutput
from src.application.mappers.job_posting_mapper import JobPostingMapper
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.services.hard_disqualifier_filter import HardDisqualifierFilter
from src.domain.value_objects.job_requirements import JobRequirements


class ListEligibleJobPostings:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        profile_repository: ProfileRepository,
        disqualifier_filter: HardDisqualifierFilter | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._profile_repository = profile_repository
        self._filter = disqualifier_filter or HardDisqualifierFilter()

    async def execute(
        self, profile_id: str, *, limit: int = 100
    ) -> list[JobPostingOutput]:
        profile = await self._profile_repository.get_by_id(profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id)

        postings = await self._job_posting_repository.list_active(limit=limit)
        eligible = [
            posting
            for posting in postings
            if self._filter.evaluate(
                profile, posting.requirements or JobRequirements()
            ).qualifies
        ]
        return [JobPostingMapper.to_output(posting) for posting in eligible]
