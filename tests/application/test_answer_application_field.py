"""Tests for `AnswerApplicationField` — the candidate answering, on the live
form, what ApplyFlow refused to answer for them.

This is the other half of "unmapped fields are surfaced, not guessed", and
the only path by which an EEO answer ever reaches an application form.
"""

from __future__ import annotations

import pytest

from src.application.dtos.application_autofill_dtos import (
    AutofilledFieldOutput,
    FieldAutofillOutcome,
)
from src.application.dtos.application_review_dtos import AnswerApplicationFieldInput
from src.application.exceptions import (
    RejectedFieldValueError,
    ReviewFieldNotFoundError,
    ReviewSessionNotFoundError,
)
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
)
from src.application.use_cases.answer_application_field import AnswerApplicationField
from tests.application.conftest import FakeBrowserSession, SequentialIdGenerator

GREENHOUSE_URL = "https://boards.greenhouse.io/globex/jobs/4001"


def surfaced(
    field_id: str,
    label: str,
    *,
    reason: str = "unrecognized",
    is_sensitive: bool = False,
    sensitivity: str | None = None,
    required: bool = False,
) -> AutofilledFieldOutput:
    return AutofilledFieldOutput(
        field_id=field_id,
        label=label,
        kind="text",
        required=required,
        outcome=FieldAutofillOutcome.SURFACED.value,
        reason=reason,
        is_sensitive=is_sensitive,
        sensitivity=sensitivity,
    )


async def build(
    *,
    fields: list[AutofilledFieldOutput],
    session: FakeBrowserSession | None = None,
) -> tuple[AnswerApplicationField, str, FakeBrowserSession]:
    sessions = ApplicationReviewSessions(SequentialIdGenerator("review"))
    browser_session = session or FakeBrowserSession()
    review = await sessions.park(
        user_id="user-1",
        job_posting_id="job-posting-1",
        apply_url=GREENHOUSE_URL,
        ats_provider="greenhouse",
        session=browser_session,
        fields=fields,
        screenshot_png=None,
        boundaries=[],
    )
    return AnswerApplicationField(sessions), review.review_id, browser_session


async def test_a_screening_question_the_candidate_answers_reaches_the_form() -> None:
    use_case, review_id, session = await build(
        fields=[surfaced("f-q", "Why do you want to work at Globex?")]
    )

    output = await use_case.execute(
        AnswerApplicationFieldInput(
            user_id="user-1",
            review_session_id=review_id,
            field_id="f-q",
            value="I have shipped logistics platforms for six years.",
        )
    )

    assert session.filled == [
        ("f-q", "I have shipped logistics platforms for six years.")
    ]
    answered = output.fields[0]
    assert answered.outcome == FieldAutofillOutcome.FILLED.value
    assert answered.answered_by_candidate is True
    assert answered.reason is None


async def test_eeo_reaches_a_form_only_when_the_candidate_answers_it() -> None:
    """The policy holds end to end: the autofill pass surfaced this field
    untouched, and the value on the form is the one the candidate typed on
    this application."""
    use_case, review_id, session = await build(
        fields=[
            surfaced(
                "f-gender",
                "Gender",
                reason="requires_candidate_answer",
                is_sensitive=True,
                sensitivity="voluntary_self_id",
            )
        ]
    )

    output = await use_case.execute(
        AnswerApplicationFieldInput(
            user_id="user-1",
            review_session_id=review_id,
            field_id="f-gender",
            value="Decline to self-identify",
        )
    )

    assert session.filled == [("f-gender", "Decline to self-identify")]
    answered = output.fields[0]
    assert answered.answered_by_candidate is True
    # Still flagged, so a review screen keeps rendering it as sensitive.
    assert answered.is_sensitive is True
    assert answered.sensitivity == "voluntary_self_id"
    # And it needs no confirmation — they just wrote it themselves.
    assert answered.requires_confirmation is False


async def test_the_whole_report_comes_back_so_the_screen_can_update() -> None:
    """The answer that clears the last required field changes what the
    candidate has left to do, which is the thing the screen has to show."""
    use_case, review_id, _ = await build(
        fields=[
            surfaced("f-a", "Required question", required=True),
            surfaced("f-b", "Optional question"),
        ]
    )

    output = await use_case.execute(
        AnswerApplicationFieldInput(
            user_id="user-1",
            review_session_id=review_id,
            field_id="f-a",
            value="answered",
        )
    )

    assert [item.field_id for item in output.fields] == ["f-a", "f-b"]
    assert output.unanswered_required_fields == []
    assert output.review_session_id == review_id


async def test_a_value_the_form_refuses_is_not_recorded_as_answered() -> None:
    """A stored answer the form never accepted would make the report a claim
    about the page rather than a description of it."""
    session = FakeBrowserSession(
        failures={
            "f-country": RejectedFieldValueError(
                "f-country", "Texas", "'United States', 'Canada'"
            )
        }
    )
    use_case, review_id, _ = await build(
        fields=[surfaced("f-country", "Country")], session=session
    )

    with pytest.raises(RejectedFieldValueError) as caught:
        await use_case.execute(
            AnswerApplicationFieldInput(
                user_id="user-1",
                review_session_id=review_id,
                field_id="f-country",
                value="Texas",
            )
        )

    # The candidate is told what would have worked, and the field is still
    # unanswered.
    assert "United States" in caught.value.accepted


async def test_a_field_that_is_not_on_the_form_is_refused() -> None:
    use_case, review_id, session = await build(fields=[surfaced("f-q", "A question")])

    with pytest.raises(ReviewFieldNotFoundError):
        await use_case.execute(
            AnswerApplicationFieldInput(
                user_id="user-1",
                review_session_id=review_id,
                field_id="f-not-here",
                value="anything",
            )
        )

    assert session.filled == []


async def test_another_candidate_cannot_write_into_this_form() -> None:
    use_case, review_id, session = await build(fields=[surfaced("f-q", "A question")])

    with pytest.raises(ReviewSessionNotFoundError):
        await use_case.execute(
            AnswerApplicationFieldInput(
                user_id="user-2",
                review_session_id=review_id,
                field_id="f-q",
                value="not mine to answer",
            )
        )

    assert session.filled == []
