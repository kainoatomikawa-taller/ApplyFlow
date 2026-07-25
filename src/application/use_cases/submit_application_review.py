"""SubmitApplicationReview use case — the candidate submits. The only path in
the system that marks an application as sent.

What it does, precisely
-----------------------
Re-reads the hand-off state, asks the domain to record the submission (which
refuses while any blocker stands), stores the result, and hands back the URL the
candidate finishes on. Nothing here touches a browser and nothing here presses a
button on a portal — ApplyFlow cannot, because the harness discovers no submit
controls (see `BrowserAutomationPort`). The candidate sends the application;
this records that they did, and refuses to let them do it while a legal
declaration is unconfirmed or the portal is still walled.

Why the gate is re-checked here
-------------------------------
The review payload already carries `can_submit`, and a UI disables its button
on it. That is a convenience, not the rule. This use case recomputes the
blockers against the hand-off state *as of now*, so:

- a client that ignores `can_submit` and posts anyway is refused;
- a hand-off raised between the candidate reading the page and pressing submit
  is caught (a portal can put up a wall at any time);
- the refusal is one rule in one place, rather than a UI check and a server
  check that can drift apart.

Submitting twice is refused rather than absorbed. The second attempt gets a
`BusinessRuleViolationError` from `ReviewStatus`, which the interface turns into
a 409 — the honest answer to a double-clicked button is "that already
happened", not a rewritten submission time.
"""

from __future__ import annotations

import logging

from src.application.dtos.application_review_dtos import (
    SubmitApplicationReviewInput,
    SubmitApplicationReviewOutput,
)
from src.application.mappers.application_review_mapper import ApplicationReviewMapper
from src.domain.exceptions import ApplicationReviewNotFoundError
from src.domain.repositories.application_review_repository import (
    ApplicationReviewRepository,
)
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository

logger = logging.getLogger(__name__)


class SubmitApplicationReview:
    def __init__(
        self,
        review_repository: ApplicationReviewRepository,
        handoff_repository: PortalHandoffRepository,
    ) -> None:
        self._review_repository = review_repository
        self._handoff_repository = handoff_repository

    async def execute(
        self, dto: SubmitApplicationReviewInput
    ) -> SubmitApplicationReviewOutput:
        review = await self._review_repository.get_by_id(dto.review_id)
        if review is None or review.user_id != dto.user_id:
            raise ApplicationReviewNotFoundError(dto.review_id)

        open_handoff = await self._handoff_repository.get_open_for_job(
            user_id=dto.user_id, job_posting_id=review.job_posting_id
        )
        # Raises BusinessRuleViolationError listing every blocker, or if this
        # review was already submitted.
        submitted = review.record_submission(
            has_open_handoff=open_handoff is not None, note=dto.note
        )
        await self._review_repository.update(submitted)

        # Ids and counts only — the answers and the candidate's note are what
        # went onto a real application, and neither is ever logged.
        logger.info(
            "The candidate submitted an application: review=%s posting=%s "
            "answers=%d",
            submitted.id,
            submitted.job_posting_id,
            len(submitted.answers),
        )
        return SubmitApplicationReviewOutput(
            review=ApplicationReviewMapper.to_output(submitted, has_open_handoff=False),
            apply_url=submitted.apply_url,
        )
