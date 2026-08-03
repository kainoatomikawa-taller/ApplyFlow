"""Tests for the review-and-submit routes: auth gating, the three-step open
sequence, what each response serializes, and how each failure maps to a status.

The sequence is the part worth pinning. Opening a review runs the hard-stop
check, then the fill pass, then the review — and when the check hands off, the
fill pass must not run at all. That ordering is the difference between "we
stopped before touching the portal" and "we filled a form we then refused to
hand over", so it is asserted directly rather than inferred from the response.

Uses FastAPI's dependency_overrides with in-memory fake use cases, so no real
database or browser is required.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.application.dtos.application_autofill_dtos import ApplicationAutofillOutput
from src.application.dtos.application_review_dtos import (
    ApplicationReviewOutput,
    OpenApplicationReviewOutput,
    ReviewedAnswerOutput,
    SubmissionBlockerOutput,
    SubmitApplicationReviewOutput,
)
from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.portal_handoff_dtos import (
    HardStopOutput,
    InspectApplicationPortalOutput,
    PortalHandoffOutput,
)
from src.application.exceptions import (
    BrowserNavigationError,
    UnsupportedAtsFormError,
    UseCaseError,
)
from src.domain.exceptions import (
    ApplicationReviewNotFoundError,
    BusinessRuleViolationError,
    JobPostingNotFoundError,
    NoActiveApplicationReviewError,
    ProfileNotFoundError,
)
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_application_review_use_case,
    get_autofill_application_form_use_case,
    get_current_user,
    get_inspect_application_portal_use_case,
    get_open_application_review_use_case,
    get_revise_reviewed_answer_use_case,
    get_submit_application_review_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_AT = datetime(2026, 7, 25, 10, 0, tzinfo=UTC)
_APPLY_URL = "https://boards.greenhouse.io/globex/jobs/4001"


class _FakeUseCase:
    def __init__(self, output=None, error=None) -> None:
        self._output = output
        self._error = error
        self.calls = 0
        self.received = None

    async def execute(self, dto):
        self.calls += 1
        self.received = dto
        if self._error is not None:
            raise self._error
        return self._output


def _answer(**overrides) -> ReviewedAnswerOutput:
    defaults = {
        "key": "f0",
        "label": "Full name",
        "widget_kind": "text",
        "value": "Dana Reyes",
        "required": True,
        "origin": "autofilled",
        "slot": "full_name",
        "sensitivity": None,
        "is_sensitive": False,
        "needs_decision": False,
        "explanation": "",
    }
    defaults.update(overrides)
    return ReviewedAnswerOutput(**defaults)


def _review(**overrides) -> ApplicationReviewOutput:
    defaults = {
        "id": "review-1",
        "job_posting_id": "job-1",
        "apply_url": _APPLY_URL,
        "ats_provider": "greenhouse",
        "status": "in_review",
        "is_open": True,
        "created_at": _AT,
        "answers": [_answer()],
        "blockers": [],
        "can_submit": True,
        "handoff": None,
        "unanswered_required_keys": [],
        "screenshot_captured": True,
    }
    defaults.update(overrides)
    return ApplicationReviewOutput(**defaults)


def _handoff() -> PortalHandoffOutput:
    return PortalHandoffOutput(
        id="handoff-1",
        job_posting_id="job-1",
        apply_url=_APPLY_URL,
        paused_url="https://globex.example.com/login",
        status="awaiting_user",
        is_open=True,
        created_at=_AT,
        last_detected_at=_AT,
        hard_stops=[
            HardStopOutput(
                kind="account_wall",
                refusal_reason="This portal wants credentials.",
                human_action="Open the portal yourself and sign in.",
                evidence=["the form presents 1 password field"],
            )
        ],
    )


def _provide(use_case: _FakeUseCase):
    """An override that takes no parameters and closes over the fake.

    Deliberately not `lambda uc=use_case: uc`: FastAPI reads a parameter with a
    default as a *request* parameter, so the fake would be validated into a copy
    and the assertions here would inspect an object the route never touched.
    """

    def provide() -> _FakeUseCase:
        return use_case

    return provide


def _client(overrides: dict) -> TestClient:
    """A client with `get_current_user` stubbed and each named dependency
    replaced. Keyed by the dependency callable itself, which is how FastAPI
    addresses overrides."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    for dependency, use_case in overrides.items():
        app.dependency_overrides[dependency] = _provide(use_case)
    return TestClient(app)


def _open_client(
    *,
    inspect: _FakeUseCase | None = None,
    autofill: _FakeUseCase | None = None,
    open_review: _FakeUseCase | None = None,
) -> tuple[TestClient, _FakeUseCase, _FakeUseCase, _FakeUseCase]:
    """A client wired for the three-step open sequence, defaulting each step to
    the happy path so a test only states the one it is about."""
    inspect = inspect or _FakeUseCase(
        output=InspectApplicationPortalOutput(
            job_posting_id="job-1",
            apply_url=_APPLY_URL,
            landed_url=_APPLY_URL,
            is_handed_off=False,
        )
    )
    autofill = autofill or _FakeUseCase(
        output=ApplicationAutofillOutput(
            job_posting_id="job-1",
            apply_url=_APPLY_URL,
            ats_provider="greenhouse",
            fields=[],
            screenshot_png=b"\x89PNG fake",
        )
    )
    open_review = open_review or _FakeUseCase(
        output=OpenApplicationReviewOutput(
            job_posting_id="job-1",
            review=_review(),
            screenshot_png=b"\x89PNG fake",
        )
    )
    client = _client(
        {
            get_inspect_application_portal_use_case: inspect,
            get_autofill_application_form_use_case: autofill,
            get_open_application_review_use_case: open_review,
        }
    )
    return client, inspect, autofill, open_review


# ---- auth -------------------------------------------------------------------


def test_every_review_route_requires_authentication():
    client = TestClient(create_app())

    assert client.post("/api/job-postings/job-1/review").status_code == 401
    assert client.get("/api/job-postings/job-1/review").status_code == 401
    assert (
        client.post(
            "/api/application-reviews/review-1/answers/f0",
            json={"action": "confirm"},
        ).status_code
        == 401
    )
    assert (
        client.post("/api/application-reviews/review-1/submit", json={}).status_code
        == 401
    )


# ---- opening a review -------------------------------------------------------


def test_opening_a_review_fills_the_form_and_returns_it():
    client, inspect, autofill, _ = _open_client()

    response = client.post("/api/job-postings/job-1/review")

    assert response.status_code == 200
    body = response.json()
    assert body["review"]["id"] == "review-1"
    assert body["review"]["can_submit"] is True
    assert body["review"]["answers"][0]["value"] == "Dana Reyes"
    assert body["screenshot_base64"] is not None
    # Checked first, filled second.
    assert inspect.calls == 1
    assert autofill.calls == 1


def test_a_hard_stop_returns_the_hand_off_and_never_fills_the_form():
    """The ordering *is* the guarantee: a walled portal is not filled at all."""
    client, _, autofill, open_review = _open_client(
        inspect=_FakeUseCase(
            output=InspectApplicationPortalOutput(
                job_posting_id="job-1",
                apply_url=_APPLY_URL,
                landed_url="https://globex.example.com/login",
                is_handed_off=True,
                handoff=_handoff(),
            )
        )
    )

    response = client.post("/api/job-postings/job-1/review")

    assert response.status_code == 200
    body = response.json()
    assert body["review"] is None
    assert body["handoff"]["hard_stops"][0]["kind"] == "account_wall"
    assert body["handoff"]["hard_stops"][0]["human_action"]
    assert autofill.calls == 0
    assert open_review.calls == 0


def test_the_open_sequence_is_scoped_to_the_authenticated_user():
    client, inspect, autofill, open_review = _open_client()

    client.post("/api/job-postings/job-1/review")

    for use_case in (inspect, autofill, open_review):
        assert use_case.received.user_id == "user-123"


def test_an_unsupported_portal_is_a_422_that_says_to_apply_by_hand():
    client, _, _, _ = _open_client(
        autofill=_FakeUseCase(
            error=UnsupportedAtsFormError(
                job_posting_id="job-1", apply_url="https://workday.example.com/apply"
            )
        )
    )

    response = client.post("/api/job-postings/job-1/review")

    assert response.status_code == 422
    assert "by hand" in response.json()["detail"]


def test_a_form_with_no_fields_is_a_422():
    client, _, _, _ = _open_client(
        open_review=_FakeUseCase(
            error=UseCaseError("The application form presented no fields to review.")
        )
    )

    assert client.post("/api/job-postings/job-1/review").status_code == 422


def test_an_unknown_posting_or_missing_profile_is_a_404():
    for error in (JobPostingNotFoundError("job-9"), ProfileNotFoundError("user-123")):
        client, _, _, _ = _open_client(autofill=_FakeUseCase(error=error))

        assert client.post("/api/job-postings/job-1/review").status_code == 404


def test_a_portal_that_will_not_load_is_a_502():
    client, _, _, _ = _open_client(
        inspect=_FakeUseCase(
            error=BrowserNavigationError(_APPLY_URL, "it did not load within 30s")
        )
    )

    assert client.post("/api/job-postings/job-1/review").status_code == 502


# ---- reading a review -------------------------------------------------------


def test_the_review_in_progress_is_readable():
    use_case = _FakeUseCase(
        output=_review(
            answers=[
                _answer(),
                _answer(
                    key="f1",
                    label="Gender",
                    value="",
                    origin="unanswered",
                    slot="eeo_self_identification",
                    sensitivity="voluntary_self_id",
                    is_sensitive=True,
                    needs_decision=True,
                    explanation="ApplyFlow never answers this one.",
                ),
            ],
            blockers=[
                SubmissionBlockerOutput(
                    kind="pending_sensitive_decision",
                    detail="'Gender' is voluntary self-identification.",
                    field_key="f1",
                    field_label="Gender",
                )
            ],
            can_submit=False,
            unanswered_required_keys=["f1"],
        )
    )
    client = _client({get_application_review_use_case: use_case})

    response = client.get("/api/job-postings/job-1/review")

    assert response.status_code == 200
    body = response.json()
    assert body["can_submit"] is False
    assert body["blockers"][0]["field_key"] == "f1"
    # Sensitivity is carried, so a UI never has to infer it from the slot name.
    assert body["answers"][1]["sensitivity"] == "voluntary_self_id"
    assert body["answers"][1]["needs_decision"] is True
    assert body["unanswered_required_keys"] == ["f1"]


def test_a_posting_with_nothing_filled_yet_is_a_404():
    use_case = _FakeUseCase(error=NoActiveApplicationReviewError("job-1"))
    client = _client({get_application_review_use_case: use_case})

    assert client.get("/api/job-postings/job-1/review").status_code == 404


# ---- revising an answer -----------------------------------------------------


def test_each_action_reaches_the_use_case_with_the_field_it_names():
    for action, value in (("set", "Dana R. Reyes"), ("confirm", ""), ("decline", "")):
        use_case = _FakeUseCase(output=_review())
        client = _client({get_revise_reviewed_answer_use_case: use_case})

        response = client.post(
            "/api/application-reviews/review-1/answers/f0",
            json={"action": action, "value": value},
        )

        assert response.status_code == 200, action
        assert use_case.received.action == action
        assert use_case.received.field_key == "f0"
        assert use_case.received.review_id == "review-1"
        assert use_case.received.user_id == "user-123"


def test_the_whole_review_comes_back_after_one_decision():
    """One decision can change what is blocking submit, so the client should not
    have to re-fetch to notice."""
    use_case = _FakeUseCase(output=_review(can_submit=True, blockers=[]))
    client = _client({get_revise_reviewed_answer_use_case: use_case})

    body = client.post(
        "/api/application-reviews/review-1/answers/f0", json={"action": "confirm"}
    ).json()

    assert body["can_submit"] is True
    assert body["answers"][0]["key"] == "f0"


def test_an_unrecognized_action_is_rejected_before_the_use_case():
    use_case = _FakeUseCase(output=_review())
    client = _client({get_revise_reviewed_answer_use_case: use_case})

    response = client.post(
        "/api/application-reviews/review-1/answers/f0",
        json={"action": "approve-everything"},
    )

    assert response.status_code == 422
    assert use_case.calls == 0


def test_editing_a_submitted_review_is_a_409():
    use_case = _FakeUseCase(
        error=BusinessRuleViolationError(
            "This application was already submitted, so its answers can no longer "
            "be edited."
        )
    )
    client = _client({get_revise_reviewed_answer_use_case: use_case})

    response = client.post(
        "/api/application-reviews/review-1/answers/f0",
        json={"action": "set", "value": "x"},
    )

    assert response.status_code == 409
    assert "already submitted" in response.json()["detail"]


def test_someone_elses_review_is_a_404():
    use_case = _FakeUseCase(error=ApplicationReviewNotFoundError("review-9"))
    client = _client({get_revise_reviewed_answer_use_case: use_case})

    assert (
        client.post(
            "/api/application-reviews/review-9/answers/f0", json={"action": "confirm"}
        ).status_code
        == 404
    )


# ---- submitting -------------------------------------------------------------


def test_submitting_returns_the_record_and_where_to_finish():
    use_case = _FakeUseCase(
        output=SubmitApplicationReviewOutput(
            review=_review(
                status="submitted_by_user",
                is_open=False,
                can_submit=False,
                submitted_at=_AT,
                submission_note="sent from my laptop",
            ),
            apply_url=_APPLY_URL,
        )
    )
    client = _client({get_submit_application_review_use_case: use_case})

    response = client.post(
        "/api/application-reviews/review-1/submit",
        json={"note": "sent from my laptop"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review"]["status"] == "submitted_by_user"
    assert body["review"]["is_open"] is False
    assert body["review"]["submission_note"] == "sent from my laptop"
    # ApplyFlow does not press the portal's button, so it says where to go.
    assert body["apply_url"] == _APPLY_URL
    assert use_case.received.user_id == "user-123"


def test_submitting_with_a_blocker_standing_is_a_409_that_names_it():
    """The server-side gate: a client that ignored `can_submit` gets refused,
    and told what is missing."""
    use_case = _FakeUseCase(
        error=BusinessRuleViolationError(
            "This application is not ready to submit: 'Gender' is voluntary "
            "self-identification. ApplyFlow never answers it — answer it "
            "yourself or decline it."
        )
    )
    client = _client({get_submit_application_review_use_case: use_case})

    response = client.post("/api/application-reviews/review-1/submit", json={})

    assert response.status_code == 409
    assert "voluntary" in response.json()["detail"]


def test_submitting_twice_is_a_409():
    use_case = _FakeUseCase(
        error=BusinessRuleViolationError(
            "Cannot move this application review from 'submitted_by_user' to "
            "'submitted_by_user'."
        )
    )
    client = _client({get_submit_application_review_use_case: use_case})

    assert (
        client.post("/api/application-reviews/review-1/submit", json={}).status_code
        == 409
    )


def test_submitting_someone_elses_review_is_a_404():
    use_case = _FakeUseCase(error=ApplicationReviewNotFoundError("review-9"))
    client = _client({get_submit_application_review_use_case: use_case})

    assert (
        client.post("/api/application-reviews/review-9/submit", json={}).status_code
        == 404
    )


def test_an_over_long_note_is_rejected_before_the_use_case():
    use_case = _FakeUseCase(output=None)
    client = _client({get_submit_application_review_use_case: use_case})

    response = client.post(
        "/api/application-reviews/review-1/submit", json={"note": "x" * 1001}
    )

    assert response.status_code == 422
    assert use_case.calls == 0
