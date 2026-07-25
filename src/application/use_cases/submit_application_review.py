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

Logging into the tracker, and why it cannot fail this use case
--------------------------------------------------------------
A submitted review is also the event that puts an application into the tracker
(`SubmittedApplicationLog`), carrying references to the exact resume and cover
letter that went out. The order here is deliberate: the review is marked
submitted and persisted *first*, and only then is the tracker written.

If that write fails, this use case still succeeds. The candidate is about to
send — or has just sent — a real application to a real employer, and reporting a
failure because a projection of that event did not land would tell them
something false about their own application, and would invite a retry that
`record_submission` refuses anyway. So the failure is logged at ERROR with the
ids needed to repair it, and the submission stands.

What makes that safe rather than a silent hole is that logging is keyed on the
review id and is idempotent: replaying it for the same review produces the one
record, so a repair pass is a no-op where the log already succeeded. The failure
is recoverable precisely because a second attempt cannot double-count.
"""

from __future__ import annotations

import logging

from src.application.dtos.application_review_dtos import (
    SubmitApplicationReviewInput,
    SubmitApplicationReviewOutput,
)
from src.application.mappers.application_review_mapper import ApplicationReviewMapper
from src.application.services.submitted_application_log import SubmittedApplicationLog
from src.domain.entities.application_review import ApplicationReview
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
        submitted_application_log: SubmittedApplicationLog,
    ) -> None:
        self._review_repository = review_repository
        self._handoff_repository = handoff_repository
        self._log = submitted_application_log

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

        await self._log_into_tracker(submitted)

        return SubmitApplicationReviewOutput(
            review=ApplicationReviewMapper.to_output(submitted, has_open_handoff=False),
            apply_url=submitted.apply_url,
        )

    async def _log_into_tracker(self, submitted: ApplicationReview) -> None:
        """Record the submission in the tracker, without letting a failure here
        misreport an application that has already been sent.

        Keyed on the review id, so this is idempotent: a repair pass over a
        submission that failed to log produces the one record, and does nothing
        where the log already succeeded. See the module docstring.
        """
        # `record_submission` guarantees this is set on a submitted review.
        assert submitted.submitted_at is not None
        try:
            await self._log.record(
                user_id=submitted.user_id,
                job_posting_id=submitted.job_posting_id,
                submission_key=submitted.id,
                applied_at=submitted.submitted_at,
            )
        except Exception:  # noqa: BLE001 - see below; the submission must stand
            # Deliberately broad, and deliberately not re-raised. The candidate's
            # application is with the employer; telling them the submission
            # failed would be false, and a retry is refused by the domain
            # anyway. Everything needed to replay the log is in this line, and
            # replaying it is safe because logging is idempotent.
            logger.exception(
                "Failed to log a submitted application into the tracker. The "
                "submission itself stands and is recorded on the review. "
                "Replay with review=%s user=%s posting=%s",
                submitted.id,
                submitted.user_id,
                submitted.job_posting_id,
            )
