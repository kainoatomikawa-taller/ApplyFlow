"""Tests for `SubmitApplicationForm` — the only code in ApplyFlow that can
cause an application to be sent.

Almost every test here asserts that **nothing was pressed**. That is the
point: the gates are the feature, and the failure mode they exist to prevent
(an application going out that the candidate had not seen, completed, or
approved) is invisible from our side and permanent from theirs. `pressed ==
[]` is therefore the assertion that carries the most weight in this file.
"""

from __future__ import annotations

import pytest

from src.application.dtos.application_autofill_dtos import (
    ApplicationBoundaryOutput,
    AutofilledFieldOutput,
    FieldAutofillOutcome,
)
from src.application.dtos.application_review_dtos import SubmitApplicationFormInput
from src.application.exceptions import (
    AmbiguousSubmitControlError,
    ApplicationHandoffRequiredError,
    BrowserAutomationError,
    IncompleteApplicationError,
    ReviewSessionNotFoundError,
    StaleFormFieldError,
    SubmitControlNotPressableError,
    SubmitControlUnavailableError,
    UnconfirmedSensitiveFieldsError,
)
from src.application.ports.browser_automation_port import SubmitControl
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
)
from src.application.use_cases.submit_application_form import SubmitApplicationForm
from src.domain.value_objects.page_signals import PageSignals
from tests.application.conftest import FakeBrowserSession, SequentialIdGenerator

GREENHOUSE_URL = "https://boards.greenhouse.io/globex/jobs/4001"

SUBMIT = SubmitControl(handle="s1-submit", label="Submit application")

CONFIRMATION_SIGNALS = PageSignals(
    url="https://boards.greenhouse.io/globex/jobs/4001/confirmation",
    visible_text="Thanks — your application has been received.",
)


def filled(
    field_id: str,
    label: str,
    *,
    required: bool = False,
    requires_confirmation: bool = False,
) -> AutofilledFieldOutput:
    return AutofilledFieldOutput(
        field_id=field_id,
        label=label,
        kind="text",
        required=required,
        outcome=FieldAutofillOutcome.FILLED.value,
        value="something",
        is_sensitive=requires_confirmation,
        sensitivity="legal_attestation" if requires_confirmation else None,
        requires_confirmation=requires_confirmation,
    )


def surfaced(
    field_id: str, label: str, *, required: bool = False
) -> AutofilledFieldOutput:
    return AutofilledFieldOutput(
        field_id=field_id,
        label=label,
        kind="text",
        required=required,
        outcome=FieldAutofillOutcome.SURFACED.value,
        reason="unrecognized",
    )


async def build(
    *,
    fields: list[AutofilledFieldOutput] | None = None,
    session: FakeBrowserSession | None = None,
    boundaries: list[ApplicationBoundaryOutput] | None = None,
) -> tuple[SubmitApplicationForm, str, FakeBrowserSession, ApplicationReviewSessions]:
    sessions = ApplicationReviewSessions(SequentialIdGenerator("review"))
    browser_session = session or FakeBrowserSession(
        signals_after_press=CONFIRMATION_SIGNALS
    )
    review = await sessions.park(
        user_id="user-1",
        job_posting_id="job-posting-1",
        apply_url=GREENHOUSE_URL,
        ats_provider="greenhouse",
        session=browser_session,
        fields=fields if fields is not None else [filled("f-1", "First Name")],
        screenshot_png=None,
        boundaries=boundaries or [],
    )
    return (
        SubmitApplicationForm(sessions),
        review.review_id,
        browser_session,
        sessions,
    )


def submit_input(review_id: str, **overrides: object) -> SubmitApplicationFormInput:
    defaults: dict[str, object] = {
        "user_id": "user-1",
        "review_session_id": review_id,
    }
    defaults.update(overrides)
    return SubmitApplicationFormInput(**defaults)  # type: ignore[arg-type]


# ---- The application goes out -------------------------------------------------


async def test_a_reviewed_application_is_submitted_when_the_candidate_says_so() -> None:
    use_case, review_id, session, _ = await build()

    output = await use_case.execute(submit_input(review_id))

    assert session.pressed == [SUBMIT.handle]
    assert output.pressed_control == "Submit application"
    assert output.job_posting_id == "job-posting-1"
    assert output.submitted_at.tzinfo is not None
    assert output.is_confirmed_sent is True


async def test_what_the_portal_answered_with_comes_back_for_the_candidate() -> None:
    use_case, review_id, _, _ = await build()

    output = await use_case.execute(submit_input(review_id))

    assert output.final_url.endswith("/confirmation")
    assert "received" in output.confirmation_excerpt
    assert output.screenshot_png is not None


async def test_a_confirmed_sensitive_answer_is_submitted() -> None:
    """The gate is a gate, not a wall: a candidate who has looked at their
    work-authorization answer and approved it can send the application."""
    use_case, review_id, session, _ = await build(
        fields=[
            filled("f-1", "First Name"),
            filled("f-auth", "Authorized to work?", requires_confirmation=True),
        ]
    )

    output = await use_case.execute(
        submit_input(review_id, confirmed_field_ids=("f-auth",))
    )

    assert session.pressed == [SUBMIT.handle]
    assert output.is_confirmed_sent is True


async def test_the_session_is_released_once_the_application_is_sent() -> None:
    """A submitted application has nothing left to review, and the browser
    holding it must not linger for the rest of its lease."""
    use_case, review_id, session, sessions = await build()

    await use_case.execute(submit_input(review_id))

    assert session.closed is True
    with pytest.raises(ReviewSessionNotFoundError):
        await sessions.acquire(review_id, user_id="user-1")


async def test_an_application_cannot_be_submitted_twice() -> None:
    use_case, review_id, session, _ = await build()

    await use_case.execute(submit_input(review_id))
    with pytest.raises(ReviewSessionNotFoundError):
        await use_case.execute(submit_input(review_id))

    assert session.pressed == [SUBMIT.handle]


# ---- Nobody else's application ------------------------------------------------


async def test_another_candidate_cannot_submit_this_application() -> None:
    use_case, review_id, session, _ = await build()

    with pytest.raises(ReviewSessionNotFoundError):
        await use_case.execute(submit_input(review_id, user_id="user-2"))

    assert session.pressed == []


async def test_a_review_that_expired_cannot_be_submitted() -> None:
    sessions = ApplicationReviewSessions(
        SequentialIdGenerator("review"), ttl_seconds=0.0
    )
    session = FakeBrowserSession()
    review = await sessions.park(
        user_id="user-1",
        job_posting_id="job-posting-1",
        apply_url=GREENHOUSE_URL,
        ats_provider="greenhouse",
        session=session,
        fields=[filled("f-1", "First Name")],
        screenshot_png=None,
        boundaries=[],
    )

    with pytest.raises(ReviewSessionNotFoundError):
        await SubmitApplicationForm(sessions).execute(submit_input(review.review_id))

    assert session.pressed == []


# ---- The boundary gate --------------------------------------------------------


async def test_a_captcha_on_the_page_refuses_the_submission() -> None:
    session = FakeBrowserSession(
        signals=PageSignals(
            url=GREENHOUSE_URL,
            visible_text="Apply",
            frame_urls=("https://www.google.com/recaptcha/api2/anchor",),
        )
    )
    use_case, review_id, session, _ = await build(session=session)

    with pytest.raises(ApplicationHandoffRequiredError) as caught:
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []
    assert [boundary.kind for boundary in caught.value.boundaries] == ["captcha"]
    assert caught.value.apply_url == GREENHOUSE_URL
    assert "CAPTCHA" in caught.value.boundaries[0].instruction


async def test_a_challenge_that_appeared_after_filling_is_still_caught() -> None:
    """The reason the scan is re-run at submit time rather than trusted from
    the autofill pass: portals add a challenge when a form is completed
    faster than a person would."""
    session = FakeBrowserSession(
        signals=PageSignals(
            url=GREENHOUSE_URL,
            visible_text="Please verify you are human before submitting.",
        )
    )
    # The pass that filled this form saw a clean page.
    use_case, review_id, session, _ = await build(session=session, boundaries=[])

    with pytest.raises(ApplicationHandoffRequiredError):
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []


async def test_a_signature_request_refuses_the_submission() -> None:
    session = FakeBrowserSession(
        signals=PageSignals(
            url=GREENHOUSE_URL, visible_text="Please draw your signature below."
        )
    )
    use_case, review_id, session, _ = await build(session=session)

    with pytest.raises(ApplicationHandoffRequiredError) as caught:
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []
    assert [boundary.kind for boundary in caught.value.boundaries] == ["signature"]


async def test_a_refused_submission_leaves_the_review_open() -> None:
    """Nothing was sent, so the candidate keeps their filled form — they can
    finish it in their own browser from the same page."""
    session = FakeBrowserSession(
        signals=PageSignals(
            url=GREENHOUSE_URL, visible_text="Please draw your signature below."
        )
    )
    use_case, review_id, session, sessions = await build(session=session)

    with pytest.raises(ApplicationHandoffRequiredError):
        await use_case.execute(submit_input(review_id))

    assert session.closed is False
    assert await sessions.acquire(review_id, user_id="user-1") is not None


# ---- The confirmation gate ----------------------------------------------------


async def test_an_unconfirmed_legal_answer_refuses_the_submission() -> None:
    """Work authorization derived from the candidate's stored record is still
    a declaration they are accountable for making to this employer."""
    use_case, review_id, session, _ = await build(
        fields=[
            filled("f-1", "First Name"),
            filled("f-auth", "Authorized to work?", requires_confirmation=True),
        ]
    )

    with pytest.raises(UnconfirmedSensitiveFieldsError) as caught:
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []
    assert caught.value.labels == ("Authorized to work?",)


async def test_confirming_the_wrong_field_does_not_clear_the_gate() -> None:
    use_case, review_id, session, _ = await build(
        fields=[
            filled("f-auth", "Authorized to work?", requires_confirmation=True),
            filled("f-visa", "Visa type", requires_confirmation=True),
        ]
    )

    with pytest.raises(UnconfirmedSensitiveFieldsError) as caught:
        await use_case.execute(
            submit_input(review_id, confirmed_field_ids=("f-auth", "f-not-a-field"))
        )

    assert session.pressed == []
    assert caught.value.labels == ("Visa type",)


async def test_an_unlabelled_sensitive_field_is_still_named_in_the_refusal() -> None:
    """A refusal that says `''` is unactionable; the widget kind at least
    points the candidate at the right part of the form."""
    use_case, review_id, _, _ = await build(
        fields=[filled("f-auth", "   ", requires_confirmation=True)]
    )

    with pytest.raises(UnconfirmedSensitiveFieldsError) as caught:
        await use_case.execute(submit_input(review_id))

    assert caught.value.labels == ("an unlabelled text field",)


# ---- The completeness gate ----------------------------------------------------


async def test_an_unanswered_required_field_refuses_the_submission() -> None:
    """Refused here rather than sent for the portal to reject: a rejected
    submission on several portals comes back with the uploads dropped."""
    use_case, review_id, session, _ = await build(
        fields=[
            filled("f-1", "First Name"),
            surfaced("f-q", "Why Globex?", required=True),
        ]
    )

    with pytest.raises(IncompleteApplicationError) as caught:
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []
    assert caught.value.labels == ("Why Globex?",)


async def test_an_optional_field_left_blank_does_not_block_the_submission() -> None:
    use_case, review_id, session, _ = await build(
        fields=[filled("f-1", "First Name"), surfaced("f-q", "Anything else?")]
    )

    await use_case.execute(submit_input(review_id))

    assert session.pressed == [SUBMIT.handle]


async def test_a_required_field_answered_by_the_candidate_clears_the_gate() -> None:
    sessions = ApplicationReviewSessions(SequentialIdGenerator("review"))
    session = FakeBrowserSession(signals_after_press=CONFIRMATION_SIGNALS)
    review = await sessions.park(
        user_id="user-1",
        job_posting_id="job-posting-1",
        apply_url=GREENHOUSE_URL,
        ats_provider="greenhouse",
        session=session,
        fields=[surfaced("f-q", "Why Globex?", required=True)],
        screenshot_png=None,
        boundaries=[],
    )
    review.record_answer("f-q", "Because of the logistics platform.")

    await SubmitApplicationForm(sessions).execute(submit_input(review.review_id))

    assert session.pressed == [SUBMIT.handle]


async def test_a_required_field_the_portal_refused_still_blocks_submission() -> None:
    """`not_accepted` means the value never reached the page. The field is
    unanswered however good the mapping was."""
    refused = AutofilledFieldOutput(
        field_id="f-state",
        label="State",
        kind="select",
        required=True,
        outcome=FieldAutofillOutcome.NOT_ACCEPTED.value,
        value="Texas",
        detail="The form accepts: 'TX', 'CA'.",
    )
    use_case, review_id, session, _ = await build(fields=[refused])

    with pytest.raises(IncompleteApplicationError) as caught:
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []
    assert caught.value.labels == ("State",)


# ---- Choosing what to press ---------------------------------------------------


async def test_a_form_offering_two_submissions_will_not_be_guessed_at() -> None:
    """"Submit application" and "Submit and create an account" are both
    submissions. Choosing would pick a side effect nobody agreed to."""
    session = FakeBrowserSession(
        submit_controls=(
            SUBMIT,
            SubmitControl(handle="s1-account", label="Submit and create an account"),
        )
    )
    use_case, review_id, session, _ = await build(session=session)

    with pytest.raises(AmbiguousSubmitControlError) as caught:
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []
    assert caught.value.available == (
        "Submit application",
        "Submit and create an account",
    )


async def test_naming_the_control_resolves_the_ambiguity() -> None:
    session = FakeBrowserSession(
        submit_controls=(
            SubmitControl(handle="s1-account", label="Submit and create an account"),
            SUBMIT,
        ),
        signals_after_press=CONFIRMATION_SIGNALS,
    )
    use_case, review_id, session, _ = await build(session=session)

    output = await use_case.execute(
        submit_input(review_id, submit_control_label="submit application")
    )

    # Matched on case and whitespace only — and never on a prefix, which is
    # how a candidate would end up creating an account they never asked for.
    assert session.pressed == [SUBMIT.handle]
    assert output.pressed_control == "Submit application"


async def test_naming_a_control_that_is_not_there_is_refused() -> None:
    use_case, review_id, session, _ = await build()

    with pytest.raises(SubmitControlUnavailableError) as caught:
        await use_case.execute(
            submit_input(review_id, submit_control_label="Send it now")
        )

    assert session.pressed == []
    assert caught.value.available == ("Submit application",)


async def test_a_form_with_nothing_pressable_hands_off() -> None:
    """A portal that submits from script exposes no submit control. Clicking
    the nearest button-shaped thing on a real application is not a
    fallback."""
    session = FakeBrowserSession(submit_controls=())
    use_case, review_id, session, _ = await build(session=session)

    with pytest.raises(SubmitControlUnavailableError):
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []


# ---- When the press itself fails ----------------------------------------------


async def test_a_control_that_will_not_take_the_press_keeps_the_review() -> None:
    """Nothing was sent, so the candidate's filled form is exactly where it
    was and retrying is safe."""
    session = FakeBrowserSession(
        press_error=SubmitControlNotPressableError(
            SUBMIT.handle, "it is behind a cookie banner"
        )
    )
    use_case, review_id, session, sessions = await build(session=session)

    with pytest.raises(SubmitControlNotPressableError):
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []
    assert session.closed is False
    assert await sessions.acquire(review_id, user_id="user-1") is not None


async def test_a_page_that_moved_under_the_control_refuses_the_press() -> None:
    session = FakeBrowserSession(
        press_error=StaleFormFieldError(
            SUBMIT.handle, "a different control is now in its place"
        )
    )
    use_case, review_id, session, _ = await build(session=session)

    with pytest.raises(StaleFormFieldError):
        await use_case.execute(submit_input(review_id))

    assert session.pressed == []


# ---- Not overclaiming afterwards ----------------------------------------------


async def test_a_challenge_after_the_press_is_reported_not_smoothed_over() -> None:
    """The submission may not have landed. Saying it did would be the worst
    possible lie this flow could tell."""
    session = FakeBrowserSession(
        signals_after_press=PageSignals(
            url=GREENHOUSE_URL,
            visible_text="Before we can accept this, verify you are human.",
        )
    )
    use_case, review_id, session, _ = await build(session=session)

    output = await use_case.execute(submit_input(review_id))

    assert session.pressed == [SUBMIT.handle]
    assert output.is_confirmed_sent is False
    assert [boundary.kind for boundary in output.outstanding_boundaries] == ["captcha"]


async def test_a_post_submission_account_offer_is_not_read_as_a_login_wall() -> None:
    """Portals routinely offer "create an account to track your application"
    on the confirmation page. Reporting a completed application as possibly
    unsent is its own harm, so the post-press read looks at the page and not
    at its fields."""
    session = FakeBrowserSession(
        signals_after_press=PageSignals(
            url="https://boards.greenhouse.io/globex/thanks",
            visible_text=(
                "Thanks — your application has been received. Want to create "
                "an account to track it?"
            ),
        )
    )
    use_case, review_id, _, _ = await build(session=session)

    output = await use_case.execute(submit_input(review_id))

    assert output.outstanding_boundaries == []
    assert output.is_confirmed_sent is True


async def test_a_submission_survives_a_failed_screenshot() -> None:
    """The application has already been sent; losing the screenshot loses the
    candidate their proof, not their submission."""
    session = FakeBrowserSession(
        screenshot_error=BrowserAutomationError("the page crashed"),
        signals_after_press=CONFIRMATION_SIGNALS,
    )
    use_case, review_id, session, _ = await build(session=session)

    output = await use_case.execute(submit_input(review_id))

    assert session.pressed == [SUBMIT.handle]
    assert output.screenshot_png is None
    assert output.is_confirmed_sent is True
