"""ReviseReviewedAnswer use case — one decision by the candidate about one
field of a filled application.

Three actions, one use case, because they are three forms of the same act: the
candidate settling a field. Splitting them would mean three routes that must
stay in step about ownership checks, about what a submitted review refuses, and
about how the submit gate is recomputed afterwards.

- **set** — their own answer, replacing whatever was there. An empty value is
  read as a decline rather than stored as a blank of unknown intent (see
  `ReviewedAnswer.answered`).
- **confirm** — the answer as it stands is right and they are willing to send
  it. The path for a legal declaration ApplyFlow filled from their record.
- **decline** — leave it deliberately blank. Always available, which is what
  keeps "voluntary" honest on an EEO question and keeps a candidate from being
  stuck on a field they do not want to answer.

Every one of them settles a sensitive field, so any of the three clears that
field's blocker. What no code path can do is clear it *without* the candidate:
there is no bulk "approve all", and nothing else in the application calls these
methods.

The response carries the whole review, not just the field that changed. A
decision can change what stands between the candidate and submitting, and a
client that had to re-fetch to notice would show a stale gate in between.
"""

from __future__ import annotations

from src.application.dtos.application_review_dtos import (
    ApplicationReviewOutput,
    ReviseReviewedAnswerInput,
)
from src.application.exceptions import UseCaseError
from src.application.mappers.application_review_mapper import ApplicationReviewMapper
from src.application.mappers.portal_handoff_mapper import PortalHandoffMapper
from src.domain.entities.application_review import ApplicationReview
from src.domain.exceptions import ApplicationReviewNotFoundError
from src.domain.repositories.application_review_repository import (
    ApplicationReviewRepository,
)
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository

#: What a caller may ask for. Kept as data so the error message can list them.
_ACTIONS = ("set", "confirm", "decline")


class ReviseReviewedAnswer:
    def __init__(
        self,
        review_repository: ApplicationReviewRepository,
        handoff_repository: PortalHandoffRepository,
    ) -> None:
        self._review_repository = review_repository
        self._handoff_repository = handoff_repository

    async def execute(self, dto: ReviseReviewedAnswerInput) -> ApplicationReviewOutput:
        review = await self._review_repository.get_by_id(dto.review_id)
        if review is None or review.user_id != dto.user_id:
            # Somebody else's review reads as absent rather than forbidden, so
            # this route cannot be used to discover which ids exist.
            raise ApplicationReviewNotFoundError(dto.review_id)

        revised = self._apply(review, dto)
        await self._review_repository.update(revised)

        handoff = await self._handoff_repository.get_open_for_job(
            user_id=dto.user_id, job_posting_id=revised.job_posting_id
        )
        return ApplicationReviewMapper.to_output(
            revised,
            handoff=PortalHandoffMapper.to_output(handoff) if handoff else None,
            has_open_handoff=handoff is not None,
        )

    @staticmethod
    def _apply(
        review: ApplicationReview, dto: ReviseReviewedAnswerInput
    ) -> ApplicationReview:
        """Route the action to the entity, which owns what each one means.

        Raises `ReviewedAnswerNotFoundError` for a key this review does not
        have, and `BusinessRuleViolationError` for a review already submitted —
        both from the entity, so the rules hold wherever they are reached from.
        """
        action = dto.action.strip().casefold()
        if action == "set":
            return review.with_answer(dto.field_key, dto.value)
        if action == "confirm":
            return review.with_confirmation(dto.field_key)
        if action == "decline":
            return review.with_declined(dto.field_key)
        raise UseCaseError(
            f"'{dto.action}' is not something that can be done to an answer. "
            f"Expected one of: {', '.join(_ACTIONS)}."
        )
