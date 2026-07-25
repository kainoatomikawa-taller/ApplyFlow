"""Tests for the review-and-submit use cases.

Four behaviours carry the flow, and each is asserted end to end against
in-memory stores:

1. a fill report becomes a review the candidate can work with — every field,
   in page order, with the ones ApplyFlow refused explained;
2. every sensitive field arrives undecided, and only the candidate's own action
   settles it;
3. an open hard-stop hand-off means there is no review at all, and blocks
   submission if one is raised later;
4. submitting is the candidate's act, happens once, and freezes what was
   approved.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.dtos.application_autofill_dtos import (
    ApplicationAutofillOutput,
    AutofilledFieldOutput,
    FieldAutofillOutcome,
)
from src.application.dtos.application_review_dtos import (
    GetApplicationReviewInput,
    OpenApplicationReviewInput,
    ReviseReviewedAnswerInput,
    SubmitApplicationReviewInput,
)
from src.application.exceptions import UseCaseError
from src.application.use_cases.get_application_review import GetApplicationReview
from src.application.use_cases.open_application_review import OpenApplicationReview
from src.application.use_cases.revise_reviewed_answer import ReviseReviewedAnswer
from src.application.use_cases.submit_application_review import SubmitApplicationReview
from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.exceptions import (
    ApplicationReviewNotFoundError,
    BusinessRuleViolationError,
    NoActiveApplicationReviewError,
    ReviewedAnswerNotFoundError,
)
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind
from tests.application.conftest import (
    InMemoryPortalHandoffRepository,
    SequentialIdGenerator,
)

_APPLY_URL = "https://boards.greenhouse.io/globex/jobs/4001"
_USER = "user-1"
_JOB = "job-1"


def field(
    label: str,
    *,
    outcome: FieldAutofillOutcome = FieldAutofillOutcome.FILLED,
    value: str | None = None,
    required: bool = False,
    slot: str | None = None,
    sensitivity: str | None = None,
    reason: str | None = None,
    detail: str | None = None,
    kind: str = "text",
) -> AutofilledFieldOutput:
    return AutofilledFieldOutput(
        label=label,
        kind=kind,
        required=required,
        outcome=outcome.value,
        slot=slot,
        value=value,
        reason=reason,
        detail=detail,
        is_sensitive=sensitivity is not None,
        sensitivity=sensitivity,
        requires_confirmation=(
            sensitivity is not None and outcome is FieldAutofillOutcome.FILLED
        ),
    )


def report(*fields: AutofilledFieldOutput, screenshot: bytes | None = b"PNG"):
    return ApplicationAutofillOutput(
        job_posting_id=_JOB,
        apply_url=_APPLY_URL,
        ats_provider="greenhouse",
        fields=list(fields) or [field("Full name", value="Dana Reyes")],
        screenshot_png=screenshot,
    )


def _handoff() -> PortalHandoff:
    return PortalHandoff.raise_for(
        handoff_id="handoff-1",
        user_id=_USER,
        job_posting_id=_JOB,
        apply_url=_APPLY_URL,
        paused_url="https://globex.example.com/login",
        hard_stops=(
            HardStop(
                kind=HardStopKind.ACCOUNT_WALL,
                evidence=("the form presents 1 password field",),
            ),
        ),
        detected_at=datetime(2026, 7, 25, 9, 0, tzinfo=UTC),
    )


def _open_use_case(review_repository, handoff_repository) -> OpenApplicationReview:
    return OpenApplicationReview(
        review_repository=review_repository,
        handoff_repository=handoff_repository,
        id_generator=SequentialIdGenerator(prefix="review"),
    )


async def _open(review_repository, handoff_repository, *fields):
    return await _open_use_case(review_repository, handoff_repository).execute(
        OpenApplicationReviewInput(
            user_id=_USER, job_posting_id=_JOB, autofill=report(*fields)
        )
    )


# ---- opening a review --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_review_carries_every_field_in_page_order(
    review_repository, handoff_repository
):
    output = await _open(
        review_repository,
        handoff_repository,
        field("Full name", value="Dana Reyes"),
        field("Email", value="dana@example.com", required=True),
        field(
            "How did you hear about us?",
            outcome=FieldAutofillOutcome.SURFACED,
            reason="unrecognized",
        ),
    )

    assert output.review is not None
    labels = [answer.label for answer in output.review.answers]
    assert labels == ["Full name", "Email", "How did you hear about us?"]
    assert output.review.status == "in_review"
    assert output.review.apply_url == _APPLY_URL


@pytest.mark.asyncio
async def test_filled_and_unfilled_fields_are_distinguishable(
    review_repository, handoff_repository
):
    output = await _open(
        review_repository,
        handoff_repository,
        field("Full name", value="Dana Reyes"),
        field(
            "Preferred name",
            outcome=FieldAutofillOutcome.SURFACED,
            reason="no_profile_data",
        ),
    )

    assert output.review is not None
    autofilled, unanswered = output.review.answers
    assert autofilled.origin == "autofilled"
    assert autofilled.value == "Dana Reyes"
    assert unanswered.origin == "unanswered"
    assert unanswered.value == ""
    # And the candidate is told why, in words they can act on.
    assert "profile does not answer this" in unanswered.explanation


@pytest.mark.asyncio
async def test_a_value_the_portal_refused_is_not_shown_as_the_answer(
    review_repository, handoff_repository
):
    """The mapping was right and the value was wrong. Showing it as filled would
    tell the candidate their form is complete when the portal already said no."""
    output = await _open(
        review_repository,
        handoff_repository,
        field(
            "State",
            outcome=FieldAutofillOutcome.NOT_ACCEPTED,
            value="California",
            detail="The form accepts: CA, TX, NY.",
        ),
    )

    assert output.review is not None
    answer = output.review.answers[0]
    assert answer.value == ""
    assert answer.origin == "unanswered"
    assert "tried 'California'" in answer.explanation
    assert "CA, TX, NY" in answer.explanation


@pytest.mark.asyncio
async def test_the_review_is_persisted_so_the_candidate_can_come_back(
    review_repository, handoff_repository
):
    output = await _open(review_repository, handoff_repository)

    assert output.review is not None
    stored = review_repository.reviews[output.review.id]
    assert stored.user_id == _USER
    assert stored.job_posting_id == _JOB
    assert stored.is_open is True


@pytest.mark.asyncio
async def test_the_screenshot_travels_with_the_response_only(
    review_repository, handoff_repository
):
    """Proof for the session that captured it: the review records that one was
    taken, and the bytes are not stored."""
    output = await _open(review_repository, handoff_repository)

    assert output.screenshot_png == b"PNG"
    assert output.review is not None
    assert output.review.screenshot_captured is True


@pytest.mark.asyncio
async def test_re_filling_replaces_the_review_in_progress(
    review_repository, handoff_repository
):
    """One review per posting at a time: a fresh pass supersedes the answers the
    candidate had not submitted rather than competing with them."""
    # One generator across both passes, so the second review gets its own id —
    # exactly as `UuidIdGenerator` would in production.
    opener = _open_use_case(review_repository, handoff_repository)

    def _input(name: str) -> OpenApplicationReviewInput:
        return OpenApplicationReviewInput(
            user_id=_USER,
            job_posting_id=_JOB,
            autofill=report(field("Full name", value=name)),
        )

    first = await opener.execute(_input("Dana"))
    second = await opener.execute(_input("Dana Reyes"))

    assert first.review is not None and second.review is not None
    assert second.review.id != first.review.id
    assert first.review.id not in review_repository.reviews
    assert review_repository.superseded == [(_USER, _JOB), (_USER, _JOB)]


@pytest.mark.asyncio
async def test_a_form_that_presented_nothing_is_refused_rather_than_reviewed(
    review_repository, handoff_repository
):
    with pytest.raises(UseCaseError, match="no fields to review"):
        await _open_use_case(review_repository, handoff_repository).execute(
            OpenApplicationReviewInput(
                user_id=_USER,
                job_posting_id=_JOB,
                autofill=ApplicationAutofillOutput(
                    job_posting_id=_JOB,
                    apply_url=_APPLY_URL,
                    ats_provider="greenhouse",
                    fields=[],
                ),
            )
        )


@pytest.mark.asyncio
async def test_a_report_for_another_posting_is_refused(
    review_repository, handoff_repository
):
    """It would store one job's answers against another, and the resulting
    review is an expensive place to discover that."""
    with pytest.raises(UseCaseError, match="not 'job-2'"):
        await _open_use_case(review_repository, handoff_repository).execute(
            OpenApplicationReviewInput(
                user_id=_USER, job_posting_id="job-2", autofill=report()
            )
        )


# ---- sensitive fields --------------------------------------------------------


@pytest.mark.asyncio
async def test_sensitive_fields_arrive_undecided_and_block_submission(
    review_repository, handoff_repository
):
    output = await _open(
        review_repository,
        handoff_repository,
        field("Full name", value="Dana Reyes"),
        field(
            "Authorized to work in the US?",
            value="Yes",
            slot="work_authorization",
            sensitivity="legal_attestation",
            required=True,
        ),
        field(
            "Gender",
            outcome=FieldAutofillOutcome.SURFACED,
            slot="eeo_self_identification",
            sensitivity="voluntary_self_id",
            reason="requires_candidate_answer",
        ),
    )

    assert output.review is not None
    assert output.review.can_submit is False
    pending = [a.key for a in output.review.answers if a.needs_decision]
    assert len(pending) == 2
    assert {b.kind for b in output.review.blockers} == {
        "pending_sensitive_decision"
    }
    # The EEO question is flagged as never-autofilled, not merely unanswered.
    eeo = output.review.answers[2]
    assert eeo.sensitivity == "voluntary_self_id"
    assert "never answers this one" in eeo.explanation


@pytest.mark.asyncio
async def test_confirming_and_declining_clear_the_gate(
    review_repository, handoff_repository
):
    opened = await _open(
        review_repository,
        handoff_repository,
        field(
            "Authorized to work in the US?",
            value="Yes",
            slot="work_authorization",
            sensitivity="legal_attestation",
        ),
        field(
            "Veteran status",
            outcome=FieldAutofillOutcome.SURFACED,
            slot="eeo_self_identification",
            sensitivity="voluntary_self_id",
        ),
    )
    assert opened.review is not None
    revise = ReviseReviewedAnswer(
        review_repository=review_repository, handoff_repository=handoff_repository
    )

    after_confirm = await revise.execute(
        ReviseReviewedAnswerInput(
            user_id=_USER,
            review_id=opened.review.id,
            field_key="f0",
            action="confirm",
        )
    )
    assert after_confirm.can_submit is False  # the EEO question is still open

    after_decline = await revise.execute(
        ReviseReviewedAnswerInput(
            user_id=_USER,
            review_id=opened.review.id,
            field_key="f1",
            action="decline",
        )
    )

    assert after_decline.can_submit is True
    assert after_decline.blockers == []
    assert after_decline.answers[1].origin == "declined"


@pytest.mark.asyncio
async def test_editing_an_answer_records_it_as_the_candidates(
    review_repository, handoff_repository
):
    opened = await _open(
        review_repository, handoff_repository, field("Full name", value="Dana Reyes")
    )
    assert opened.review is not None

    output = await ReviseReviewedAnswer(
        review_repository=review_repository, handoff_repository=handoff_repository
    ).execute(
        ReviseReviewedAnswerInput(
            user_id=_USER,
            review_id=opened.review.id,
            field_key="f0",
            action="set",
            value="Dana R. Reyes",
        )
    )

    assert output.answers[0].value == "Dana R. Reyes"
    assert output.answers[0].origin == "candidate"
    assert review_repository.reviews[opened.review.id].answer("f0").value == (
        "Dana R. Reyes"
    )


@pytest.mark.asyncio
async def test_an_unknown_action_is_refused(review_repository, handoff_repository):
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None

    with pytest.raises(UseCaseError, match="set, confirm, decline"):
        await ReviseReviewedAnswer(
            review_repository=review_repository,
            handoff_repository=handoff_repository,
        ).execute(
            ReviseReviewedAnswerInput(
                user_id=_USER,
                review_id=opened.review.id,
                field_key="f0",
                action="approve-everything",
            )
        )


@pytest.mark.asyncio
async def test_an_unknown_field_is_refused(review_repository, handoff_repository):
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None

    with pytest.raises(ReviewedAnswerNotFoundError):
        await ReviseReviewedAnswer(
            review_repository=review_repository,
            handoff_repository=handoff_repository,
        ).execute(
            ReviseReviewedAnswerInput(
                user_id=_USER,
                review_id=opened.review.id,
                field_key="f99",
                action="set",
                value="x",
            )
        )


@pytest.mark.asyncio
async def test_someone_elses_review_reads_as_absent(
    review_repository, handoff_repository
):
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None

    with pytest.raises(ApplicationReviewNotFoundError):
        await ReviseReviewedAnswer(
            review_repository=review_repository,
            handoff_repository=handoff_repository,
        ).execute(
            ReviseReviewedAnswerInput(
                user_id="someone-else",
                review_id=opened.review.id,
                field_key="f0",
                action="confirm",
            )
        )


# ---- hard-stop hand-offs -----------------------------------------------------


@pytest.mark.asyncio
async def test_an_open_hand_off_means_no_review_at_all(review_repository):
    """Nothing was filled, so there is nothing to review — and the hand-off is
    returned instead, with its evidence and instructions."""
    handoffs = InMemoryPortalHandoffRepository([_handoff()])

    output = await _open(review_repository, handoffs, field("Full name", value="Dana"))

    assert output.review is None
    assert output.handoff is not None
    assert output.handoff.hard_stops[0].kind == "account_wall"
    assert output.handoff.hard_stops[0].human_action
    assert output.handoff.hard_stops[0].evidence
    assert review_repository.reviews == {}


@pytest.mark.asyncio
async def test_a_hand_off_raised_after_the_review_blocks_submission(
    review_repository, handoff_repository
):
    """A portal can put up a wall at any time. The gate is recomputed on every
    read, so a review that was submittable a minute ago is not any more."""
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None and opened.review.can_submit is True

    await handoff_repository.add(_handoff())

    reread = await GetApplicationReview(
        review_repository=review_repository, handoff_repository=handoff_repository
    ).execute(GetApplicationReviewInput(user_id=_USER, job_posting_id=_JOB))

    assert reread.can_submit is False
    assert [blocker.kind for blocker in reread.blockers] == ["open_hard_stop"]
    assert reread.handoff is not None


@pytest.mark.asyncio
async def test_submitting_through_a_walled_portal_is_refused(
    review_repository, handoff_repository
):
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None
    await handoff_repository.add(_handoff())

    with pytest.raises(BusinessRuleViolationError, match="only you can do"):
        await SubmitApplicationReview(
            review_repository=review_repository,
            handoff_repository=handoff_repository,
        ).execute(
            SubmitApplicationReviewInput(user_id=_USER, review_id=opened.review.id)
        )

    assert review_repository.reviews[opened.review.id].is_open is True


# ---- reading it back ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_review_survives_a_reload_with_its_decisions_intact(
    review_repository, handoff_repository
):
    opened = await _open(
        review_repository,
        handoff_repository,
        field(
            "Authorized to work in the US?",
            value="Yes",
            slot="work_authorization",
            sensitivity="legal_attestation",
        ),
    )
    assert opened.review is not None
    await ReviseReviewedAnswer(
        review_repository=review_repository, handoff_repository=handoff_repository
    ).execute(
        ReviseReviewedAnswerInput(
            user_id=_USER,
            review_id=opened.review.id,
            field_key="f0",
            action="confirm",
        )
    )

    reread = await GetApplicationReview(
        review_repository=review_repository, handoff_repository=handoff_repository
    ).execute(GetApplicationReviewInput(user_id=_USER, job_posting_id=_JOB))

    assert reread.id == opened.review.id
    assert reread.answers[0].needs_decision is False
    assert reread.can_submit is True


@pytest.mark.asyncio
async def test_a_posting_with_nothing_filled_yet_has_no_review(
    review_repository, handoff_repository
):
    with pytest.raises(NoActiveApplicationReviewError):
        await GetApplicationReview(
            review_repository=review_repository,
            handoff_repository=handoff_repository,
        ).execute(GetApplicationReviewInput(user_id=_USER, job_posting_id=_JOB))


# ---- submitting --------------------------------------------------------------


@pytest.mark.asyncio
async def test_submitting_records_the_candidate_and_hands_back_the_portal(
    review_repository, handoff_repository
):
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None

    output = await SubmitApplicationReview(
        review_repository=review_repository, handoff_repository=handoff_repository
    ).execute(
        SubmitApplicationReviewInput(
            user_id=_USER, review_id=opened.review.id, note="sent from my laptop"
        )
    )

    assert output.review.status == "submitted_by_user"
    assert output.review.is_open is False
    assert output.review.submitted_at is not None
    assert output.review.submission_note == "sent from my laptop"
    # ApplyFlow cannot press the portal's button, so it says where to finish.
    assert output.apply_url == _APPLY_URL
    assert review_repository.reviews[opened.review.id].is_open is False


@pytest.mark.asyncio
async def test_submitting_is_refused_while_a_sensitive_field_is_undecided(
    review_repository, handoff_repository
):
    """The server-side gate, not the button's `disabled` attribute: a client
    that posts anyway gets the same refusal."""
    opened = await _open(
        review_repository,
        handoff_repository,
        field(
            "Authorized to work in the US?",
            value="Yes",
            slot="work_authorization",
            sensitivity="legal_attestation",
        ),
    )
    assert opened.review is not None

    with pytest.raises(BusinessRuleViolationError, match="legal declaration"):
        await SubmitApplicationReview(
            review_repository=review_repository,
            handoff_repository=handoff_repository,
        ).execute(
            SubmitApplicationReviewInput(user_id=_USER, review_id=opened.review.id)
        )

    assert review_repository.reviews[opened.review.id].is_open is True


@pytest.mark.asyncio
async def test_submitting_twice_is_refused(review_repository, handoff_repository):
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None
    use_case = SubmitApplicationReview(
        review_repository=review_repository, handoff_repository=handoff_repository
    )
    await use_case.execute(
        SubmitApplicationReviewInput(user_id=_USER, review_id=opened.review.id)
    )

    with pytest.raises(BusinessRuleViolationError):
        await use_case.execute(
            SubmitApplicationReviewInput(user_id=_USER, review_id=opened.review.id)
        )


@pytest.mark.asyncio
async def test_a_submitted_review_cannot_be_edited(
    review_repository, handoff_repository
):
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None
    await SubmitApplicationReview(
        review_repository=review_repository, handoff_repository=handoff_repository
    ).execute(SubmitApplicationReviewInput(user_id=_USER, review_id=opened.review.id))

    with pytest.raises(BusinessRuleViolationError, match="already submitted"):
        await ReviseReviewedAnswer(
            review_repository=review_repository,
            handoff_repository=handoff_repository,
        ).execute(
            ReviseReviewedAnswerInput(
                user_id=_USER,
                review_id=opened.review.id,
                field_key="f0",
                action="set",
                value="someone else",
            )
        )


@pytest.mark.asyncio
async def test_submitting_someone_elses_review_reads_as_absent(
    review_repository, handoff_repository
):
    opened = await _open(review_repository, handoff_repository)
    assert opened.review is not None

    with pytest.raises(ApplicationReviewNotFoundError):
        await SubmitApplicationReview(
            review_repository=review_repository,
            handoff_repository=handoff_repository,
        ).execute(
            SubmitApplicationReviewInput(
                user_id="someone-else", review_id=opened.review.id
            )
        )

    assert review_repository.reviews[opened.review.id].is_open is True
