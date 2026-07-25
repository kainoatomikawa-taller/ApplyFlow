"""Tests for ApplicationReview and the answers it holds.

The acceptance criteria this flow exists for are all invariants here rather than
UI behaviour, so this is where they are pinned:

- every field is visible and editable, including the ones ApplyFlow filled;
- no sensitive field can be passed over — confirm, change, or decline, and
  nothing else clears it;
- an open hard-stop hand-off blocks submission;
- submission happens once, is recorded as the candidate's, and freezes the
  answers that were approved.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.entities.application_review import ApplicationReview
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    ReviewedAnswerNotFoundError,
)
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot as Slot,
)
from src.domain.value_objects.application_field_slot import (
    FieldSensitivity,
)
from src.domain.value_objects.review_status import ReviewStatus
from src.domain.value_objects.reviewed_answer import AnswerOrigin, ReviewedAnswer
from src.domain.value_objects.submission_blocker import SubmissionBlockerKind

_CREATED_AT = datetime(2026, 7, 25, 10, 0, tzinfo=UTC)


def answer(
    key: str,
    *,
    label: str = "Full name",
    value: str = "",
    slot: Slot | None = None,
    sensitivity: FieldSensitivity | None = None,
    required: bool = False,
    origin: AnswerOrigin = AnswerOrigin.UNANSWERED,
    decided: bool = False,
    explanation: str = "",
) -> ReviewedAnswer:
    return ReviewedAnswer(
        key=key,
        label=label,
        widget_kind="text",
        value=value,
        slot=slot,
        sensitivity=sensitivity,
        required=required,
        origin=origin,
        decided_by_candidate=decided,
        explanation=explanation,
    )


def filled(key: str, *, label: str = "Full name", value: str = "Dana Reyes"):
    return answer(key, label=label, value=value, origin=AnswerOrigin.AUTOFILLED)


def legal(key: str, *, value: str = "Yes", origin=AnswerOrigin.AUTOFILLED):
    return answer(
        key,
        label="Are you authorized to work in the US?",
        value=value,
        slot=Slot.WORK_AUTHORIZATION,
        sensitivity=FieldSensitivity.LEGAL_ATTESTATION,
        required=True,
        origin=origin,
    )


def eeo(key: str):
    return answer(
        key,
        label="Gender",
        slot=Slot.EEO_SELF_IDENTIFICATION,
        sensitivity=FieldSensitivity.VOLUNTARY_SELF_ID,
    )


def review(*answers: ReviewedAnswer) -> ApplicationReview:
    return ApplicationReview.open_for(
        review_id="review-1",
        user_id="user-1",
        job_posting_id="job-1",
        apply_url="https://boards.greenhouse.io/globex/jobs/4001",
        ats_provider="greenhouse",
        answers=answers or (filled("f0"),),
        created_at=_CREATED_AT,
    )


# ---- what the candidate sees ------------------------------------------------


def test_a_new_review_is_open_and_carries_every_field():
    subject = review(filled("f0"), answer("f1", label="Why here?"), legal("f2"))

    assert subject.status is ReviewStatus.IN_REVIEW
    assert subject.is_open is True
    assert [item.key for item in subject.answers] == ["f0", "f1", "f2"]
    assert subject.submitted_at is None


def test_unfilled_fields_are_present_rather_than_dropped():
    """A review that hid what ApplyFlow could not answer would be a review of
    half an application."""
    subject = review(
        filled("f0"),
        answer("f1", label="How did you hear about us?", explanation="Your answer."),
    )

    unanswered = [item for item in subject.answers if not item.is_answered]

    assert [item.key for item in unanswered] == ["f1"]
    assert unanswered[0].explanation == "Your answer."


def test_sensitive_fields_are_identifiable_without_inspecting_slot_names():
    subject = review(filled("f0"), legal("f1"), eeo("f2"))

    assert [item.key for item in subject.sensitive_answers] == ["f1", "f2"]
    assert subject.answers[1].is_legal_attestation is True
    assert subject.answers[2].is_voluntary_self_id is True


def test_a_review_of_no_fields_is_refused():
    """A form that presented nothing is not something to review, and an empty
    review would suggest otherwise."""
    with pytest.raises(InvalidValueError, match="at least one answer"):
        ApplicationReview.open_for(
            review_id="review-1",
            user_id="user-1",
            job_posting_id="job-1",
            apply_url="https://boards.greenhouse.io/globex/jobs/4001",
            ats_provider="greenhouse",
            answers=(),
        )


def test_duplicate_answer_keys_are_refused():
    """A duplicate key means an edit could land on the wrong question."""
    with pytest.raises(InvalidValueError, match="unique"):
        review(filled("f0"), filled("f0", label="Email"))


# ---- editing ----------------------------------------------------------------


def test_the_candidate_can_change_a_field_applyflow_filled():
    subject = review(filled("f0", value="Dana Reyes"))

    edited = subject.with_answer("f0", "Dana R. Reyes")

    assert edited.answer("f0").value == "Dana R. Reyes"
    assert edited.answer("f0").origin is AnswerOrigin.CANDIDATE
    # And the original is untouched: a caller holding it keeps what it decided on.
    assert subject.answer("f0").value == "Dana Reyes"


def test_the_candidate_can_answer_a_field_applyflow_left_alone():
    subject = review(filled("f0"), answer("f1", label="Notes"))

    edited = subject.with_answer("f1", "Referred by Priya")

    assert edited.answer("f1").is_answered is True
    assert edited.answer("f1").origin is AnswerOrigin.CANDIDATE


def test_emptying_a_field_is_recorded_as_a_decline_not_as_a_blank():
    """"Blank because I said so" and "blank because nobody has answered" are
    different states, and only one of them settles a sensitive field."""
    subject = review(filled("f0", value="Dana Reyes"))

    edited = subject.with_answer("f0", "   ")

    assert edited.answer("f0").value == ""
    assert edited.answer("f0").origin is AnswerOrigin.DECLINED
    assert edited.answer("f0").is_answered is True


def test_editing_a_field_this_review_does_not_have_is_refused():
    with pytest.raises(ReviewedAnswerNotFoundError):
        review(filled("f0")).with_answer("f9", "anything")


def test_confirming_a_field_with_no_answer_is_refused():
    with pytest.raises(InvalidValueError, match="nothing to confirm"):
        review(eeo("f0")).with_confirmation("f0")


# ---- sensitive fields gate submission ---------------------------------------


def test_every_sensitive_field_starts_undecided():
    subject = review(filled("f0"), legal("f1"), eeo("f2"))

    assert [item.key for item in subject.answers_awaiting_decision] == ["f1", "f2"]
    assert subject.can_submit(has_open_handoff=False) is False


def test_an_ordinary_field_needs_no_decision():
    subject = review(filled("f0"))

    assert subject.answers_awaiting_decision == ()
    assert subject.can_submit(has_open_handoff=False) is True


def test_the_blockers_name_the_field_and_say_what_to_do():
    subject = review(legal("f0"), eeo("f1"))

    blockers = subject.blockers(has_open_handoff=False)

    assert [blocker.field_key for blocker in blockers] == ["f0", "f1"]
    assert all(
        blocker.kind is SubmissionBlockerKind.PENDING_SENSITIVE_DECISION
        for blocker in blockers
    )
    # The two categories are asked about differently, because they are
    # different asks.
    assert "legal declaration" in blockers[0].detail
    assert "voluntary" in blockers[1].detail


def test_confirming_a_legal_declaration_settles_it():
    subject = review(legal("f0"))

    assert subject.with_confirmation("f0").can_submit(has_open_handoff=False) is True


def test_answering_a_sensitive_field_settles_it_without_a_second_step():
    """Typing a value into a legal declaration *is* the explicit decision — a
    confirm prompt afterwards would be one gate too many on the same field."""
    subject = review(legal("f0", value="", origin=AnswerOrigin.UNANSWERED))

    edited = subject.with_answer("f0", "Yes")

    assert edited.answer("f0").needs_candidate_decision is False
    assert edited.can_submit(has_open_handoff=False) is True


def test_declining_an_eeo_question_settles_it():
    """Declining has to work, or "voluntary" is a word with no mechanism
    behind it."""
    subject = review(eeo("f0"))

    declined = subject.with_declined("f0")

    assert declined.answer("f0").origin is AnswerOrigin.DECLINED
    assert declined.can_submit(has_open_handoff=False) is True


def test_nothing_settles_a_sensitive_field_except_the_candidate():
    """No bulk approval, and no side effect of another field's edit."""
    subject = review(filled("f0"), legal("f1"))

    after_other_edit = subject.with_answer("f0", "Dana R. Reyes")

    assert after_other_edit.answer("f1").needs_candidate_decision is True


# ---- hard-stop hand-offs block submission -----------------------------------


def test_an_open_hand_off_blocks_submission_even_with_everything_decided():
    subject = review(filled("f0")).with_answer("f0", "Dana Reyes")

    blockers = subject.blockers(has_open_handoff=True)

    assert [blocker.kind for blocker in blockers] == [
        SubmissionBlockerKind.OPEN_HARD_STOP
    ]
    assert subject.can_submit(has_open_handoff=True) is False


def test_submitting_through_a_walled_portal_is_refused():
    subject = review(filled("f0"))

    with pytest.raises(BusinessRuleViolationError, match="only you can do"):
        subject.record_submission(has_open_handoff=True)


# ---- required fields are warnings, not blockers ------------------------------


def test_an_unanswered_required_field_is_a_warning_not_a_blocker():
    """`required` is only as trustworthy as the portal's markup, so it must not
    lock a candidate out of recording their own submission."""
    subject = review(
        filled("f0"), answer("f1", label="Start date", required=True)
    )

    assert [item.key for item in subject.unanswered_required_answers] == ["f1"]
    assert subject.blockers(has_open_handoff=False) == ()
    assert subject.can_submit(has_open_handoff=False) is True


def test_an_answered_required_field_is_not_reported():
    subject = review(filled("f0", label="Email", value="dana@example.com"))

    assert subject.unanswered_required_answers == ()


# ---- submission --------------------------------------------------------------


def test_submitting_records_the_candidate_as_the_submitter():
    subject = review(filled("f0"), legal("f1")).with_confirmation("f1")
    submitted_at = _CREATED_AT + timedelta(minutes=12)

    submitted = subject.record_submission(
        has_open_handoff=False, note="  sent it  ", submitted_at=submitted_at
    )

    assert submitted.status is ReviewStatus.SUBMITTED_BY_USER
    assert submitted.is_open is False
    assert submitted.submitted_at == submitted_at
    assert submitted.submission_note == "sent it"
    # The answers are preserved exactly as approved.
    assert submitted.answer("f1").value == "Yes"


def test_the_answers_are_frozen_once_submitted():
    submitted = review(filled("f0")).record_submission(has_open_handoff=False)

    for attempt in (
        lambda: submitted.with_answer("f0", "someone else"),
        lambda: submitted.with_confirmation("f0"),
        lambda: submitted.with_declined("f0"),
    ):
        with pytest.raises(BusinessRuleViolationError, match="already submitted"):
            attempt()


def test_submitting_twice_is_refused():
    submitted = review(filled("f0")).record_submission(has_open_handoff=False)

    with pytest.raises(BusinessRuleViolationError):
        submitted.record_submission(has_open_handoff=False)


def test_a_submitted_review_cannot_be_reported_as_submittable():
    submitted = review(filled("f0")).record_submission(has_open_handoff=False)

    assert submitted.can_submit(has_open_handoff=False) is False


def test_the_refusal_lists_everything_that_is_missing():
    subject = review(legal("f0"), eeo("f1"))

    with pytest.raises(BusinessRuleViolationError) as caught:
        subject.record_submission(has_open_handoff=False)

    message = str(caught.value)
    assert "legal declaration" in message
    assert "voluntary" in message


def test_an_over_long_submission_note_is_refused():
    subject = review(filled("f0"))

    with pytest.raises(InvalidValueError, match="cannot exceed"):
        subject.record_submission(
            has_open_handoff=False,
            note="x" * (ApplicationReview.MAX_NOTE_LENGTH + 1),
        )


# ---- status transitions ------------------------------------------------------


def test_only_in_review_is_open():
    assert ReviewStatus.IN_REVIEW.is_open is True
    assert ReviewStatus.SUBMITTED_BY_USER.is_open is False
    assert ReviewStatus.SUBMITTED_BY_USER.is_terminal is True


def test_a_declined_answer_cannot_carry_a_value():
    with pytest.raises(InvalidValueError, match="declined answer"):
        ReviewedAnswer(
            key="f0",
            label="Gender",
            widget_kind="select",
            value="Woman",
            origin=AnswerOrigin.DECLINED,
        )
