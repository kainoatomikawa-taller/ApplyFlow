"""AnswerApplicationField use case — writes the candidate's own answer into
one field of a parked application form.

The other half of "unmapped fields are surfaced, not guessed". Surfacing a
field is only useful if the candidate can then answer it, and this is where
that answer lands: on the same live page ApplyFlow filled, in the field it
surfaced, without re-opening the portal or re-filling anything.

It is also the *only* path by which an EEO self-identification answer ever
reaches an application form. `decide_sensitive_field` refuses those
unconditionally, and nothing in the autofill pass can override that; a
candidate who chooses to disclose does it here, per application, in their
own words. An answer that arrives through this use case is by definition
theirs, so it is recorded as `answered_by_candidate` and needs no further
confirmation before submission.

What it will not do
-------------------
It does not decide anything about the value. A form that refuses it
(`RejectedFieldValueError` — a select whose options are "Yes"/"No" handed
"Absolutely") raises, carrying what the field *would* accept, rather than
quietly storing an answer that never reached the page. The candidate is at a
screen waiting; telling them beats recording a lie about what the form now
says.
"""

from __future__ import annotations

import logging

from src.application.dtos.application_autofill_dtos import ApplicationAutofillOutput
from src.application.dtos.application_review_dtos import AnswerApplicationFieldInput
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
)

logger = logging.getLogger(__name__)


class AnswerApplicationField:
    def __init__(self, review_sessions: ApplicationReviewSessions) -> None:
        self._review_sessions = review_sessions

    async def execute(
        self, dto: AnswerApplicationFieldInput
    ) -> ApplicationAutofillOutput:
        """Write `dto.value` into the named field and return the updated report.

        The whole report comes back rather than just the field, because the
        answer can change what the candidate has left to do — this is the
        answer that clears the last required field, and the screen that has
        to show it.
        """
        review = await self._review_sessions.acquire(
            dto.review_session_id, user_id=dto.user_id
        )
        field = review.field_by_id(dto.field_id)

        # The write happens first and the record second: a stored answer the
        # form never accepted would make the report a claim about the page
        # rather than a description of it.
        await review.session.fill(field.field_id, dto.value)
        review.record_answer(dto.field_id, dto.value)

        # The value itself is never logged — it is the candidate's answer on
        # a real application, up to and including EEO data.
        logger.info(
            "Candidate answered a surfaced field (review_id=%s, "
            "job_posting_id=%s, slot=%s, sensitivity=%s).",
            review.review_id,
            review.job_posting_id,
            field.slot,
            field.sensitivity,
        )
        return review.to_output()
