"""GetApplicationReview use case — the review a candidate is in the middle of
for one posting.

The read that makes the flow survivable. A candidate opens the review, goes to
check what their visa type is actually called, comes back to a reloaded page —
and everything they had already decided is still decided, including the
sensitive fields they confirmed, which are precisely the ones nobody should be
asked about twice.

The submit gate is recomputed on every read rather than stored: whether a
hand-off is open for this portal can change while the candidate is reading (they
may have just resolved one), and a stale `can_submit` would either block
somebody who is ready or offer a submit button that the submit route then
refuses.
"""

from __future__ import annotations

from src.application.dtos.application_review_dtos import (
    ApplicationReviewOutput,
    GetApplicationReviewInput,
)
from src.application.mappers.application_review_mapper import ApplicationReviewMapper
from src.application.mappers.portal_handoff_mapper import PortalHandoffMapper
from src.domain.exceptions import NoActiveApplicationReviewError
from src.domain.repositories.application_review_repository import (
    ApplicationReviewRepository,
)
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository


class GetApplicationReview:
    def __init__(
        self,
        review_repository: ApplicationReviewRepository,
        handoff_repository: PortalHandoffRepository,
    ) -> None:
        self._review_repository = review_repository
        self._handoff_repository = handoff_repository

    async def execute(
        self, dto: GetApplicationReviewInput
    ) -> ApplicationReviewOutput:
        review = await self._review_repository.get_active_for_job(
            user_id=dto.user_id, job_posting_id=dto.job_posting_id
        )
        if review is None:
            raise NoActiveApplicationReviewError(dto.job_posting_id)

        handoff = await self._handoff_repository.get_open_for_job(
            user_id=dto.user_id, job_posting_id=dto.job_posting_id
        )
        return ApplicationReviewMapper.to_output(
            review,
            handoff=PortalHandoffMapper.to_output(handoff) if handoff else None,
            has_open_handoff=handoff is not None,
        )
