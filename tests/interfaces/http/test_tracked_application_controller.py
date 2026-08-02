"""Tests for the application-tracking routes: auth gating, what each response
serializes, how the status filter reaches the use case, and how each failure maps
to a status code.

The mappings worth pinning are the three that are easy to get wrong and hard to
notice:

- a refused transition is a 409, not a 422. It is a well-formed request that the
  lifecycle does not permit, and a client distinguishes "fix your input" from
  "that move isn't available" by the code.
- an unknown status name *is* a 422 — well-formed, but naming something that
  does not exist.
- another candidate's application is a 404, identical to a missing one. Anything
  else confirms the application exists.

Uses FastAPI's dependency_overrides with in-memory fake use cases, so no real
database is required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.tracked_application_dtos import (
    ApplicationStatusChangeOutput,
    TrackedApplicationOutput,
)
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    TrackedApplicationNotFoundError,
)
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_current_user,
    get_list_applications_for_job_use_case,
    get_list_tracked_applications_use_case,
    get_tracked_application_use_case,
    get_update_application_status_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_APPLIED_AT = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


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


def _application(**overrides) -> TrackedApplicationOutput:
    defaults = {
        "id": "app-1",
        "job_posting_id": "job-1",
        "company_name": "Globex",
        "role_title": "Senior Backend Engineer",
        "applied_at": _APPLIED_AT,
        "status": "interviewing",
        "is_open": True,
        "current_status_since": _APPLIED_AT + timedelta(days=7),
        "resume_document_id": "doc-resume",
        "cover_letter_document_id": "doc-letter",
        "status_history": [
            ApplicationStatusChangeOutput(status="applied", changed_at=_APPLIED_AT),
            ApplicationStatusChangeOutput(
                status="interviewing",
                changed_at=_APPLIED_AT + timedelta(days=7),
                previous_status="applied",
                note="recruiter screen",
            ),
        ],
        "updated_at": _APPLIED_AT + timedelta(days=7),
    }
    defaults.update(overrides)
    return TrackedApplicationOutput(**defaults)


def _provide(use_case: _FakeUseCase):
    """Wrap a fake as a zero-argument dependency.

    It has to take no parameters: FastAPI inspects an override's signature, so a
    `lambda uc=use_case: uc` would be read as declaring a query parameter named
    `uc` rather than as a closure over the fake — and the route would then be
    handed something other than the fake, silently.
    """

    def provider() -> _FakeUseCase:
        return use_case

    return provider


def _client(overrides: dict | None = None) -> TestClient:
    """An app with the tracker's use cases replaced by fakes, and auth
    satisfied — the routes under test are all behind `get_current_user`."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    for dependency, use_case in (overrides or {}).items():
        app.dependency_overrides[dependency] = _provide(use_case)
    return TestClient(app)


# ---- auth -------------------------------------------------------------------


def test_the_tracker_routes_require_a_bearer_token() -> None:
    client = TestClient(create_app())

    assert client.get("/api/tracked-applications").status_code == 401
    assert client.get("/api/tracked-applications/app-1").status_code == 401
    assert (
        client.patch(
            "/api/tracked-applications/app-1/status", json={"status": "offer"}
        ).status_code
        == 401
    )


# ---- reading ----------------------------------------------------------------


def test_the_feed_serializes_each_application_with_its_history() -> None:
    use_case = _FakeUseCase(output=[_application()])
    client = _client({get_list_tracked_applications_use_case: use_case})

    response = client.get("/api/tracked-applications")

    assert response.status_code == 200
    body = response.json()
    assert body["open_count"] == 1
    (application,) = body["applications"]
    assert application["status"] == "interviewing"
    assert application["role_title"] == "Senior Backend Engineer"
    assert [entry["status"] for entry in application["status_history"]] == [
        "applied",
        "interviewing",
    ]
    assert application["status_history"][1]["previous_status"] == "applied"
    assert application["status_history"][0]["previous_status"] is None


def test_the_open_count_counts_only_live_applications() -> None:
    use_case = _FakeUseCase(
        output=[
            _application(id="a", is_open=True),
            _application(id="b", status="rejected", is_open=False),
            _application(id="c", status="withdrawn", is_open=False),
        ]
    )
    client = _client({get_list_tracked_applications_use_case: use_case})

    body = client.get("/api/tracked-applications").json()

    assert body["open_count"] == 1
    assert len(body["applications"]) == 3


def test_repeated_status_parameters_reach_the_use_case_as_a_filter() -> None:
    """The query-string shape a client uses for a multi-status view."""
    use_case = _FakeUseCase(output=[])
    client = _client({get_list_tracked_applications_use_case: use_case})

    client.get("/api/tracked-applications?status=applied&status=interviewing&limit=25")

    assert use_case.received.statuses == ("applied", "interviewing")
    assert use_case.received.limit == 25
    assert use_case.received.open_only is False
    assert use_case.received.user_id == _USER.subject


def test_no_status_parameter_means_no_filter() -> None:
    use_case = _FakeUseCase(output=[])
    client = _client({get_list_tracked_applications_use_case: use_case})

    client.get("/api/tracked-applications")

    assert use_case.received.statuses is None


def test_open_only_reaches_the_use_case() -> None:
    use_case = _FakeUseCase(output=[])
    client = _client({get_list_tracked_applications_use_case: use_case})

    client.get("/api/tracked-applications?open_only=true")

    assert use_case.received.open_only is True
    assert use_case.received.statuses is None


def test_an_unknown_status_in_the_query_is_unprocessable() -> None:
    use_case = _FakeUseCase(error=InvalidValueError("'ghosted' is not a status."))
    client = _client({get_list_tracked_applications_use_case: use_case})

    response = client.get("/api/tracked-applications?status=ghosted")

    assert response.status_code == 422
    assert "ghosted" in response.json()["detail"]


def test_a_limit_outside_the_allowed_range_is_rejected_by_validation() -> None:
    use_case = _FakeUseCase(output=[])
    client = _client({get_list_tracked_applications_use_case: use_case})

    assert client.get("/api/tracked-applications?limit=0").status_code == 422
    assert client.get("/api/tracked-applications?limit=501").status_code == 422
    assert use_case.calls == 0


def test_one_application_is_read_by_id() -> None:
    use_case = _FakeUseCase(output=_application())
    client = _client({get_tracked_application_use_case: use_case})

    response = client.get("/api/tracked-applications/app-1")

    assert response.status_code == 200
    assert response.json()["id"] == "app-1"
    assert use_case.received.application_id == "app-1"
    assert use_case.received.user_id == _USER.subject


def test_an_unknown_application_is_not_found() -> None:
    use_case = _FakeUseCase(error=TrackedApplicationNotFoundError("app-9"))
    client = _client({get_tracked_application_use_case: use_case})

    response = client.get("/api/tracked-applications/app-9")

    assert response.status_code == 404


def test_applications_for_one_posting_are_listed_under_by_job() -> None:
    """Under `/by-job/` so a posting id can never be read as an application
    id by the detail route."""
    use_case = _FakeUseCase(output=[_application(), _application(id="app-2")])
    client = _client({get_list_applications_for_job_use_case: use_case})

    response = client.get("/api/tracked-applications/by-job/job-1")

    assert response.status_code == 200
    assert len(response.json()["applications"]) == 2
    assert use_case.received.job_posting_id == "job-1"


# ---- updating a status ------------------------------------------------------


def test_a_status_update_returns_the_whole_application() -> None:
    """Not just the new status: the change also moves `current_status_since`,
    can close the application, and always appends to the history."""
    use_case = _FakeUseCase(output=_application())
    client = _client({get_update_application_status_use_case: use_case})

    response = client.patch(
        "/api/tracked-applications/app-1/status",
        json={"status": "interviewing", "note": "recruiter screen"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "interviewing"
    assert body["current_status_since"] is not None
    assert len(body["status_history"]) == 2
    assert use_case.received.status == "interviewing"
    assert use_case.received.note == "recruiter screen"
    assert use_case.received.application_id == "app-1"
    assert use_case.received.user_id == _USER.subject


def test_a_status_update_without_a_note_is_allowed() -> None:
    use_case = _FakeUseCase(output=_application())
    client = _client({get_update_application_status_use_case: use_case})

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "offer"}
    )

    assert response.status_code == 200
    assert use_case.received.note == ""


def test_a_refused_transition_is_a_conflict() -> None:
    """409, not 422: the request is well-formed and the lifecycle simply does
    not allow the move."""
    use_case = _FakeUseCase(
        error=BusinessRuleViolationError(
            "Cannot move application from 'rejected' to 'interviewing'."
        )
    )
    client = _client({get_update_application_status_use_case: use_case})

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "interviewing"}
    )

    assert response.status_code == 409
    assert "rejected" in response.json()["detail"]


def test_a_status_that_is_not_a_status_is_unprocessable() -> None:
    use_case = _FakeUseCase(error=InvalidValueError("'ghosted' is not a status."))
    client = _client({get_update_application_status_use_case: use_case})

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "ghosted"}
    )

    assert response.status_code == 422


def test_updating_an_application_that_is_not_this_candidates_is_not_found() -> None:
    """Indistinguishable from a missing id — anything else would confirm the
    application exists."""
    use_case = _FakeUseCase(error=TrackedApplicationNotFoundError("app-1"))
    client = _client({get_update_application_status_use_case: use_case})

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "offer"}
    )

    assert response.status_code == 404


def test_an_empty_status_is_rejected_before_the_use_case() -> None:
    use_case = _FakeUseCase(output=_application())
    client = _client({get_update_application_status_use_case: use_case})

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": ""}
    )

    assert response.status_code == 422
    assert use_case.calls == 0


def test_a_missing_status_is_rejected_before_the_use_case() -> None:
    use_case = _FakeUseCase(output=_application())
    client = _client({get_update_application_status_use_case: use_case})

    response = client.patch("/api/tracked-applications/app-1/status", json={})

    assert response.status_code == 422
    assert use_case.calls == 0


def test_an_over_long_note_is_rejected_before_the_domain_sees_it() -> None:
    use_case = _FakeUseCase(output=_application())
    client = _client({get_update_application_status_use_case: use_case})

    response = client.patch(
        "/api/tracked-applications/app-1/status",
        json={"status": "offer", "note": "x" * 1001},
    )

    assert response.status_code == 422
    assert use_case.calls == 0
