"""Tests for the autofill / review / submit router: auth gating, the shape a
review screen receives, and the status code every refusal arrives as.

Uses FastAPI's dependency_overrides with in-memory fake use cases, so no
browser and no database is involved. What is being checked here is the HTTP
contract — that a hand-off arrives with its instructions intact, that a
refusal to submit is a 409 the candidate can act on, and that nothing in this
layer can submit an application by itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.application.dtos.application_autofill_dtos import (
    ApplicationAutofillOutput,
    ApplicationBoundaryOutput,
    AutofilledFieldOutput,
    FieldAutofillOutcome,
)
from src.application.dtos.application_review_dtos import ApplicationSubmissionOutput
from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.exceptions import (
    AmbiguousSubmitControlError,
    ApplicationHandoffRequiredError,
    BrowserNavigationError,
    IncompleteApplicationError,
    RejectedFieldValueError,
    ReviewFieldNotFoundError,
    ReviewSessionNotFoundError,
    StaleFormFieldError,
    SubmitControlNotPressableError,
    SubmitControlUnavailableError,
    UnconfirmedSensitiveFieldsError,
    UnsupportedAtsFormError,
)
from src.domain.exceptions import JobPostingNotFoundError
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_answer_application_field_use_case,
    get_autofill_application_form_use_case,
    get_current_user,
    get_discard_application_review_use_case,
    get_submit_application_form_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")

AUTOFILL_URL = "/api/job-postings/job-1/autofill"
FIELD_URL = "/api/autofill-sessions/review-1/fields/f-q"
SUBMIT_URL = "/api/autofill-sessions/review-1/submit"
REVIEW_URL = "/api/autofill-sessions/review-1"

CAPTCHA_BOUNDARY = ApplicationBoundaryOutput(
    kind="captcha",
    evidence="the page loads a challenge widget from 'google.com/recaptcha'",
    instruction="Open the apply link yourself to finish and send it.",
    stopped_autofill=False,
    blocks_submission=True,
)


class _FakeUseCase:
    def __init__(self, output=None, error=None) -> None:
        self._output = output
        self._error = error
        self.received = None

    async def execute(self, dto):
        self.received = dto
        if self._error is not None:
            raise self._error
        return self._output


def field(
    field_id: str = "f-1",
    *,
    label: str = "First Name",
    outcome: FieldAutofillOutcome = FieldAutofillOutcome.FILLED,
    required: bool = False,
    value: str | None = "Dana",
    is_sensitive: bool = False,
    requires_confirmation: bool = False,
    answered_by_candidate: bool = False,
) -> AutofilledFieldOutput:
    return AutofilledFieldOutput(
        field_id=field_id,
        label=label,
        kind="text",
        required=required,
        outcome=outcome.value,
        value=value,
        is_sensitive=is_sensitive,
        sensitivity="legal_attestation" if is_sensitive else None,
        requires_confirmation=requires_confirmation,
        answered_by_candidate=answered_by_candidate,
    )


def autofill_output(**overrides) -> ApplicationAutofillOutput:
    defaults = {
        "job_posting_id": "job-1",
        "apply_url": "https://boards.greenhouse.io/globex/jobs/4001",
        "ats_provider": "greenhouse",
        "fields": [field()],
        "screenshot_png": b"\x89PNG",
        "review_session_id": "review-1",
        "review_expires_at": datetime(2026, 7, 25, 12, 15, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ApplicationAutofillOutput(**defaults)


_DEPENDENCIES = {
    "autofill": get_autofill_application_form_use_case,
    "answer": get_answer_application_field_use_case,
    "submit": get_submit_application_form_use_case,
    "discard": get_discard_application_review_use_case,
}


def _provide(use_case: _FakeUseCase):
    """A zero-argument override.

    Written out rather than as `lambda uc=use_case: uc` because FastAPI reads
    a dependency's parameters as request parameters — a defaulted argument
    there becomes a query parameter it then tries to deep-copy.
    """

    def provider() -> _FakeUseCase:
        return use_case

    return provider


def client_with(**overrides) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    for dependency, use_case in overrides.items():
        app.dependency_overrides[_DEPENDENCIES[dependency]] = _provide(use_case)
    return TestClient(app)


# ---- Auth --------------------------------------------------------------------


def test_every_route_requires_authorization():
    """Including submit, above all — an unauthenticated caller must not be
    able to send someone's application."""
    client = TestClient(create_app())

    assert client.post(AUTOFILL_URL).status_code == 401
    assert client.post(FIELD_URL, json={"value": "x"}).status_code == 401
    assert client.post(SUBMIT_URL, json={}).status_code == 401
    assert client.delete(REVIEW_URL).status_code == 401


def test_the_autofill_runs_for_the_authenticated_candidate_only():
    """The user id comes from the verified token, never from the request, so
    one candidate cannot fill a form from another's profile."""
    use_case = _FakeUseCase(output=autofill_output())
    response = client_with(autofill=use_case).post(AUTOFILL_URL)

    assert response.status_code == 200
    assert use_case.received.user_id == "user-123"
    assert use_case.received.job_posting_id == "job-1"


# ---- The filled form a review screen receives --------------------------------


def test_a_filled_form_comes_back_with_its_review_session_and_evidence():
    output = autofill_output(
        fields=[
            field("f-1", label="First Name"),
            field(
                "f-auth",
                label="Authorized to work?",
                is_sensitive=True,
                requires_confirmation=True,
                value="Yes",
            ),
            field(
                "f-q",
                label="Why Globex?",
                outcome=FieldAutofillOutcome.SURFACED,
                required=True,
                value=None,
            ),
        ]
    )
    response = client_with(autofill=_FakeUseCase(output=output)).post(AUTOFILL_URL)
    body = response.json()

    assert body["review_session_id"] == "review-1"
    assert body["ats_provider"] == "greenhouse"
    assert [item["field_id"] for item in body["fields"]] == ["f-1", "f-auth", "f-q"]
    # The screenshot crosses as base64: encoding for transport is this
    # layer's job, not the DTO's.
    assert body["screenshot_png_base64"] == "iVBORw=="
    # The two submission gates arrive named, so a client never has to
    # re-derive them to know whether its Submit button can work.
    assert body["fields_awaiting_confirmation"] == ["f-auth"]
    assert body["unanswered_required_fields"] == ["f-q"]
    assert body["can_be_submitted_here"] is True


def test_a_sensitive_field_arrives_flagged_rather_than_inferable():
    """A review UI must never have to pattern-match slot names to decide what
    to flag — an inference that, gone wrong, renders a visa declaration as an
    ordinary text box."""
    output = autofill_output(
        fields=[
            AutofilledFieldOutput(
                field_id="f-gender",
                label="Gender",
                kind="select",
                required=False,
                outcome=FieldAutofillOutcome.SURFACED.value,
                slot="eeo_gender",
                reason="requires_candidate_answer",
                is_sensitive=True,
                sensitivity="voluntary_self_id",
            )
        ]
    )

    response = client_with(autofill=_FakeUseCase(output=output)).post(AUTOFILL_URL)
    item = response.json()["fields"][0]

    assert item["is_sensitive"] is True
    assert item["sensitivity"] == "voluntary_self_id"
    assert item["reason"] == "requires_candidate_answer"
    assert item["value"] is None


def test_a_handed_off_pass_is_a_200_carrying_the_instruction():
    """ApplyFlow read the page and found something only the candidate can do.
    That is an answer to the request, not a failure of it."""
    output = autofill_output(
        fields=[],
        review_session_id=None,
        review_expires_at=None,
        boundaries=[
            ApplicationBoundaryOutput(
                kind="login",
                evidence="the page asks for a password",
                instruction="Open the apply link yourself, sign in, and try again.",
                stopped_autofill=True,
                blocks_submission=True,
            )
        ],
    )
    response = client_with(autofill=_FakeUseCase(output=output)).post(AUTOFILL_URL)
    body = response.json()

    assert response.status_code == 200
    assert body["requires_handoff"] is True
    assert body["can_be_submitted_here"] is False
    assert body["review_session_id"] is None
    assert body["boundaries"][0]["kind"] == "login"
    assert "sign in" in body["boundaries"][0]["instruction"]
    assert body["boundaries"][0]["stopped_autofill"] is True


# ---- Autofill failures --------------------------------------------------------


def test_a_missing_posting_is_a_404():
    use_case = _FakeUseCase(error=JobPostingNotFoundError("job-1"))
    assert client_with(autofill=use_case).post(AUTOFILL_URL).status_code == 404


def test_an_unsupported_portal_is_a_422():
    use_case = _FakeUseCase(
        error=UnsupportedAtsFormError("job-1", "https://globex.wd1.myworkdayjobs.com/x")
    )
    response = client_with(autofill=use_case).post(AUTOFILL_URL)

    assert response.status_code == 422
    assert "Greenhouse" in response.json()["detail"]


def test_a_portal_that_would_not_load_is_a_502():
    use_case = _FakeUseCase(
        error=BrowserNavigationError("https://boards.greenhouse.io/x", "it timed out")
    )
    assert client_with(autofill=use_case).post(AUTOFILL_URL).status_code == 502


# ---- Answering a surfaced field ----------------------------------------------


def test_the_candidates_answer_reaches_the_named_field():
    use_case = _FakeUseCase(
        output=autofill_output(
            fields=[field("f-q", label="Why Globex?", answered_by_candidate=True)]
        )
    )
    response = client_with(answer=use_case).post(
        FIELD_URL, json={"value": "Because of the logistics platform."}
    )

    assert response.status_code == 200
    assert use_case.received.field_id == "f-q"
    assert use_case.received.value == "Because of the logistics platform."
    assert use_case.received.user_id == "user-123"
    assert response.json()["fields"][0]["answered_by_candidate"] is True


def test_an_empty_answer_is_refused_before_it_reaches_the_form():
    """An empty string in a required question looks answered and asserts
    nothing."""
    use_case = _FakeUseCase(output=autofill_output())
    response = client_with(answer=use_case).post(FIELD_URL, json={"value": ""})

    assert response.status_code == 422
    assert use_case.received is None


def test_a_value_the_form_refuses_is_a_422_naming_what_it_accepts():
    use_case = _FakeUseCase(
        error=RejectedFieldValueError("f-q", "Texas", "'United States', 'Canada'")
    )
    response = client_with(answer=use_case).post(FIELD_URL, json={"value": "Texas"})

    assert response.status_code == 422
    assert "United States" in response.json()["detail"]


def test_an_unknown_review_or_field_is_a_404():
    session_gone = _FakeUseCase(error=ReviewSessionNotFoundError("review-1"))
    assert (
        client_with(answer=session_gone)
        .post(FIELD_URL, json={"value": "x"})
        .status_code
        == 404
    )

    field_gone = _FakeUseCase(error=ReviewFieldNotFoundError("review-1", "f-q"))
    assert (
        client_with(answer=field_gone).post(FIELD_URL, json={"value": "x"}).status_code
        == 404
    )


def test_a_form_that_moved_is_a_409_telling_the_candidate_to_start_again():
    use_case = _FakeUseCase(
        error=StaleFormFieldError("f-q", "a different field is now in its place")
    )
    response = client_with(answer=use_case).post(FIELD_URL, json={"value": "x"})

    assert response.status_code == 409
    assert "Nothing was sent" in response.json()["detail"]


# ---- Submitting ---------------------------------------------------------------


def test_a_submitted_application_reports_what_was_pressed_and_what_came_back():
    use_case = _FakeUseCase(
        output=ApplicationSubmissionOutput(
            job_posting_id="job-1",
            submitted_at=datetime(2026, 7, 25, 12, 5, tzinfo=UTC),
            pressed_control="Submit application",
            final_url="https://boards.greenhouse.io/globex/thanks",
            confirmation_excerpt="Thanks — your application has been received.",
            screenshot_png=b"\x89PNG",
        )
    )
    response = client_with(submit=use_case).post(
        SUBMIT_URL, json={"confirmed_field_ids": ["f-auth"]}
    )
    body = response.json()

    assert response.status_code == 200
    assert body["pressed_control"] == "Submit application"
    assert body["is_confirmed_sent"] is True
    assert "received" in body["confirmation_excerpt"]
    assert body["screenshot_png_base64"] == "iVBORw=="
    # The candidate's confirmations reach the gate that needs them.
    assert use_case.received.confirmed_field_ids == ("f-auth",)


def test_confirmations_default_to_none_rather_than_to_everything():
    """A missing `confirmed_field_ids` must mean "nothing is approved". The
    opposite default would submit legal declarations nobody had looked at."""
    use_case = _FakeUseCase(
        output=ApplicationSubmissionOutput(
            job_posting_id="job-1",
            submitted_at=datetime(2026, 7, 25, 12, 5, tzinfo=UTC),
            pressed_control="Submit application",
            final_url="https://boards.greenhouse.io/globex/thanks",
        )
    )
    client_with(submit=use_case).post(SUBMIT_URL, json={})

    assert use_case.received.confirmed_field_ids == ()


def test_a_boundary_refuses_the_submission_as_a_409_with_the_hand_off():
    use_case = _FakeUseCase(
        error=ApplicationHandoffRequiredError(
            "https://boards.greenhouse.io/globex/jobs/4001", (CAPTCHA_BOUNDARY,)
        )
    )
    response = client_with(submit=use_case).post(SUBMIT_URL, json={})
    detail = response.json()["detail"]

    assert response.status_code == 409
    assert detail["apply_url"] == "https://boards.greenhouse.io/globex/jobs/4001"
    assert detail["boundaries"][0]["kind"] == "captcha"
    # The instruction travels with the refusal: a hand-off that says what was
    # found but not what to do about it strands the candidate.
    assert "yourself" in detail["boundaries"][0]["instruction"]


def test_unconfirmed_legal_answers_refuse_the_submission_and_name_them():
    use_case = _FakeUseCase(
        error=UnconfirmedSensitiveFieldsError(("Authorized to work?", "Visa type"))
    )
    response = client_with(submit=use_case).post(SUBMIT_URL, json={})
    detail = response.json()["detail"]

    assert response.status_code == 409
    assert detail["unconfirmed_fields"] == ["Authorized to work?", "Visa type"]


def test_missing_required_answers_refuse_the_submission_and_name_them():
    use_case = _FakeUseCase(error=IncompleteApplicationError(("Why Globex?",)))
    response = client_with(submit=use_case).post(SUBMIT_URL, json={})

    assert response.status_code == 409
    assert response.json()["detail"]["unanswered_required_fields"] == ["Why Globex?"]


def test_two_submit_buttons_ask_the_candidate_which_one():
    use_case = _FakeUseCase(
        error=AmbiguousSubmitControlError(
            ("Submit application", "Submit and create an account")
        )
    )
    response = client_with(submit=use_case).post(SUBMIT_URL, json={})
    detail = response.json()["detail"]

    assert response.status_code == 409
    assert detail["submit_controls"] == [
        "Submit application",
        "Submit and create an account",
    ]


def test_a_form_with_nothing_pressable_is_a_409():
    use_case = _FakeUseCase(
        error=SubmitControlUnavailableError("the form exposes no control")
    )
    response = client_with(submit=use_case).post(SUBMIT_URL, json={})

    assert response.status_code == 409


def test_a_press_that_failed_is_a_502_and_says_nothing_was_sent():
    use_case = _FakeUseCase(
        error=SubmitControlNotPressableError("s1", "it is behind a cookie banner")
    )
    response = client_with(submit=use_case).post(SUBMIT_URL, json={})

    assert response.status_code == 502
    assert "could not be pressed" in response.json()["detail"]


def test_a_challenge_after_the_press_is_reported_on_the_200():
    """The press happened; the portal answered with a challenge. Saying the
    application was received would be the worst lie available here."""
    use_case = _FakeUseCase(
        output=ApplicationSubmissionOutput(
            job_posting_id="job-1",
            submitted_at=datetime(2026, 7, 25, 12, 5, tzinfo=UTC),
            pressed_control="Submit application",
            final_url="https://boards.greenhouse.io/globex/jobs/4001",
            outstanding_boundaries=[CAPTCHA_BOUNDARY],
        )
    )
    response = client_with(submit=use_case).post(SUBMIT_URL, json={})
    body = response.json()

    assert response.status_code == 200
    assert body["is_confirmed_sent"] is False
    assert body["outstanding_boundaries"][0]["kind"] == "captcha"


def test_an_unknown_review_session_cannot_be_submitted():
    use_case = _FakeUseCase(error=ReviewSessionNotFoundError("review-1"))
    response = client_with(submit=use_case).post(SUBMIT_URL, json={})

    assert response.status_code == 404
    assert "expired" in response.json()["detail"]


# ---- Discarding ---------------------------------------------------------------


def test_discarding_a_review_closes_it():
    use_case = _FakeUseCase()
    response = client_with(discard=use_case).delete(REVIEW_URL)

    assert response.status_code == 204
    assert response.content == b""
    assert use_case.received.review_session_id == "review-1"
    assert use_case.received.user_id == "user-123"


def test_discarding_an_unknown_review_is_a_404():
    use_case = _FakeUseCase(error=ReviewSessionNotFoundError("review-1"))
    assert client_with(discard=use_case).delete(REVIEW_URL).status_code == 404
