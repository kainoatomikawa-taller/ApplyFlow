"""DiscardApplicationReview use case — the candidate walks away from a filled
form without sending it.

Small, and worth having as its own use case rather than as a controller
calling the registry directly. A parked review holds a live browser session,
so "I changed my mind" needs to be an action the candidate can actually take;
without it the only way a session goes away is by timing out, which means a
candidate who decided against an application still costs a browser context
for the rest of its lease.

Nothing is sent, and nothing about the application is recorded: the form was
filled in a browser that is now closed, and the candidate's decision not to
apply is not ApplyFlow's to keep.
"""

from __future__ import annotations

import logging

from src.application.dtos.application_review_dtos import DiscardApplicationReviewInput
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
)

logger = logging.getLogger(__name__)


class DiscardApplicationReview:
    def __init__(self, review_sessions: ApplicationReviewSessions) -> None:
        self._review_sessions = review_sessions

    async def execute(self, dto: DiscardApplicationReviewInput) -> None:
        """Close the parked review, or raise `ReviewSessionNotFoundError`.

        Raising for an id that is not the caller's own matters here as much
        as anywhere: discard must not be usable to close someone else's
        session, or to find out whether theirs exists.
        """
        await self._review_sessions.release(
            dto.review_session_id, user_id=dto.user_id
        )
        logger.info(
            "Discarded an application review without submitting (review_id=%s).",
            dto.review_session_id,
        )
