"""OpenApplicationReview use case — turns one fill pass into something the
candidate can read, correct, and submit.

Where it sits in the flow
-------------------------
The interface layer runs three steps in order, and the order is the safety
property: check the portal for hard boundaries, fill the form, open the review.
This use case is the third, and it re-checks the first — if a hand-off is open
for this posting there is no review at all, only the hand-off, because handing
someone an application to send through a portal that is still walled is handing
them a dead end. The gate lives here rather than only in the controller so that
it holds for every caller, including the next one.

It runs no browser
------------------
It takes the pass's report as data. That keeps the whole "what does the
candidate see and what must they decide" question testable from a literal, and
it means this use case cannot accidentally touch the portal — the only thing
that writes to a form is the pass that already ran.

Re-filling replaces, never accumulates
--------------------------------------
Opening a review supersedes the one already in progress for the same posting
(`supersede_active`). Two open reviews would mean two sets of answers for one
application with nothing to say which the candidate meant. A review already
*submitted* is never touched: it records what was sent.
"""

from __future__ import annotations

import logging

from src.application.dtos.application_review_dtos import (
    OpenApplicationReviewInput,
    OpenApplicationReviewOutput,
)
from src.application.exceptions import UseCaseError
from src.application.mappers.application_review_mapper import ApplicationReviewMapper
from src.application.mappers.portal_handoff_mapper import PortalHandoffMapper
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.application_review import ApplicationReview
from src.domain.repositories.application_review_repository import (
    ApplicationReviewRepository,
)
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository

logger = logging.getLogger(__name__)


class OpenApplicationReview:
    def __init__(
        self,
        review_repository: ApplicationReviewRepository,
        handoff_repository: PortalHandoffRepository,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._review_repository = review_repository
        self._handoff_repository = handoff_repository
        self._id_generator = id_generator

    async def execute(
        self, dto: OpenApplicationReviewInput
    ) -> OpenApplicationReviewOutput:
        if dto.autofill.job_posting_id != dto.job_posting_id:
            # A report for a different posting would store one job's answers
            # against another. Caller bug, and an expensive one to debug from
            # the resulting review, so it fails here.
            raise UseCaseError(
                "The fill report is for job posting "
                f"'{dto.autofill.job_posting_id}', not '{dto.job_posting_id}'."
            )

        open_handoff = await self._handoff_repository.get_open_for_job(
            user_id=dto.user_id, job_posting_id=dto.job_posting_id
        )
        if open_handoff is not None:
            return OpenApplicationReviewOutput(
                job_posting_id=dto.job_posting_id,
                review=None,
                handoff=PortalHandoffMapper.to_output(open_handoff),
            )

        answers = ApplicationReviewMapper.answers_from_autofill(dto.autofill)
        if not answers:
            # The portal presented nothing fillable — a dead posting, an
            # interstitial, or a form that never mounted. There is nothing to
            # review, and an empty review would suggest otherwise.
            raise UseCaseError(
                "The application form at "
                f"{dto.autofill.apply_url} presented no fields to review."
            )

        await self._review_repository.supersede_active(
            user_id=dto.user_id, job_posting_id=dto.job_posting_id
        )
        review = ApplicationReview.open_for(
            review_id=self._id_generator.new_id(),
            user_id=dto.user_id,
            job_posting_id=dto.job_posting_id,
            apply_url=dto.autofill.apply_url,
            ats_provider=dto.autofill.ats_provider,
            answers=answers,
            screenshot_captured=dto.autofill.screenshot_png is not None,
        )
        await self._review_repository.add(review)

        # Counts only. The answers are what goes onto a real application (see
        # `ApplicationReview`), so none of them is ever logged.
        logger.info(
            "Opened an application review: review=%s posting=%s answers=%d "
            "awaiting_decision=%d",
            review.id,
            review.job_posting_id,
            len(review.answers),
            len(review.answers_awaiting_decision),
        )
        return OpenApplicationReviewOutput(
            job_posting_id=dto.job_posting_id,
            review=ApplicationReviewMapper.to_output(review, has_open_handoff=False),
            screenshot_png=dto.autofill.screenshot_png,
        )
