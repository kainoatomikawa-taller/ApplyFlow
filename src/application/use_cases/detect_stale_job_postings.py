"""DetectStaleJobPostings use case — sweeps a bounded batch of ACTIVE
postings, flags ones too old as STALE, and probes the rest's apply_url,
flagging confirmed or repeatedly-unreachable links as DEAD_LINK.

Intended to run as a periodic background job (see the Celery task that
wires this up) — this use case only needs to be safe to call repeatedly
and to bound its own work per call (`dto.batch_size`), so a schedule can
eventually sweep an unbounded table a few pages at a time.

One posting's checker outcome never aborts the batch —
`ApplyUrlCheckerPort.check` itself does not raise for ordinary network
failures (see that port's docstring) — and this use case additionally
guards each posting's processing so a single unexpected error can't sink
the rest of the sweep, the same defensive posture `IngestAggregatorJobs`
takes toward one company's unresolvable listing.
"""

from __future__ import annotations

from src.application.dtos.job_staleness_dtos import (
    DetectStaleJobPostingsInput,
    DetectStaleJobPostingsOutput,
)
from src.application.ports.apply_url_checker_port import ApplyUrlCheckerPort
from src.domain.entities.job_posting import JobPosting
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.job_posting_status import JobPostingStatus


class DetectStaleJobPostings:
    def __init__(
        self, repository: JobPostingRepository, url_checker: ApplyUrlCheckerPort
    ) -> None:
        self._repository = repository
        self._url_checker = url_checker

    async def execute(
        self, dto: DetectStaleJobPostingsInput
    ) -> DetectStaleJobPostingsOutput:
        postings = await self._repository.list_due_for_staleness_check(
            as_of=dto.as_of,
            recheck_after_days=dto.recheck_after_days,
            batch_size=dto.batch_size,
        )

        checked_count = 0
        newly_stale_count = 0
        newly_dead_link_count = 0
        failed_count = 0

        for posting in postings:
            try:
                became_stale, became_dead_link = await self._sweep_one(posting, dto)
            except Exception:  # noqa: BLE001 - one posting must never sink the sweep
                failed_count += 1
                continue

            checked_count += 1
            newly_stale_count += int(became_stale)
            newly_dead_link_count += int(became_dead_link)

        return DetectStaleJobPostingsOutput(
            checked_count=checked_count,
            newly_stale_count=newly_stale_count,
            newly_dead_link_count=newly_dead_link_count,
            failed_count=failed_count,
        )

    async def _sweep_one(
        self, posting: JobPosting, dto: DetectStaleJobPostingsInput
    ) -> tuple[bool, bool]:
        posting.mark_stale_if_expired(
            as_of=dto.as_of, stale_after_days=dto.stale_after_days
        )

        # Only spend a network request on postings the age check didn't
        # already remove from the active set.
        if posting.is_active:
            outcome = await self._url_checker.check(posting.apply_url)
            posting.apply_link_check(
                outcome,
                checked_at=dto.as_of,
                dead_link_after_failures=dto.dead_link_after_failures,
            )

        await self._repository.update(posting)
        return (
            posting.status == JobPostingStatus.STALE,
            posting.status == JobPostingStatus.DEAD_LINK,
        )
