"""Tests for the tracker routes: auth gating, what a row serializes, and how
each refusal maps to a status code.

Uses FastAPI's dependency_overrides with in-memory fake use cases, so no real
database is required. What the use cases themselves do is covered in
tests/application/test_tracked_application_use_cases.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.tracked_application_dtos import (
    SentDocumentOutput,
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
    get_list_tracked_applications_use_case,
    get_update_tracked_application_status_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_APPLIED_AT = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)


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


def _sent_document(**overrides) -> SentDocumentOutput:
    defaults = {
        "id": "doc-resume-1",
        "document_kind": "tailored_resume",
        "version": 2,
        "content_sha256": "a" * 64,
        "created_at": _APPLIED_AT,
    }
    defaults.update(overrides)
    return SentDocumentOutput(**defaults)


def _application(**overrides) -> TrackedApplicationOutput:
    defaults = {
        "id": "app-1",
        "job_posting_id": "job-1",
        "company_name": "Globex",
        "role_title": "Senior Platform Engineer",
        "job_location": "Austin, TX",
        "applied_at": _APPLIED_AT,
        "status": "applied",
        "is_open": True,
        "allowed_next_statuses": ["interviewing", "rejected", "withdrawn"],
        "resume": _sent_document(),
        "cover_letter": _sent_document(
            id="doc-letter-1", document_kind="cover_letter", version=1
        ),
        "created_at": _APPLIED_AT,
        "updated_at": _APPLIED_AT,
    }
    defaults.update(overrides)
    return TrackedApplicationOutput(**defaults)


def _client(dependency, use_case) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[dependency] = lambda: use_case
    return TestClient(app)


# ---- auth -------------------------------------------------------------------


def test_the_tracker_routes_require_authentication():
    client = TestClient(create_app())

    assert client.get("/api/tracked-applications").status_code == 401
    assert (
        client.patch(
            "/api/tracked-applications/app-1/status", json={"status": "interviewing"}
        ).status_code
        == 401
    )


# ---- reading the feed --------------------------------------------------------


def test_the_feed_carries_each_application_with_the_documents_that_were_sent():
    use_case = _FakeUseCase(output=[_application()])
    client = _client(get_list_tracked_applications_use_case, use_case)

    response = client.get("/api/tracked-applications")

    assert response.status_code == 200
    (row,) = response.json()
    assert row["company_name"] == "Globex"
    assert row["role_title"] == "Senior Platform Engineer"
    assert row["status"] == "applied"
    # The two references resolved into the snapshots that went out.
    assert row["resume"]["id"] == "doc-resume-1"
    assert row["resume"]["version"] == 2
    assert row["cover_letter"]["document_kind"] == "cover_letter"


def test_the_feed_never_carries_document_text():
    """The tracker lists what was sent; reading a document is a separate,
    deliberate request. Shipping the text here would spread the most
    PII-dense content in the system across every list response."""
    use_case = _FakeUseCase(output=[_application()])
    client = _client(get_list_tracked_applications_use_case, use_case)

    (row,) = client.get("/api/tracked-applications").json()

    assert "content" not in row["resume"]
    assert "content" not in row["cover_letter"]
    # The digest is there instead, so a client can still identify the exact
    # snapshot it is looking at.
    assert row["resume"]["content_sha256"] == "a" * 64


def test_an_application_sent_without_a_cover_letter_reports_none():
    use_case = _FakeUseCase(output=[_application(cover_letter=None)])
    client = _client(get_list_tracked_applications_use_case, use_case)

    (row,) = client.get("/api/tracked-applications").json()

    assert row["cover_letter"] is None
    assert row["resume"] is not None


def test_the_feed_is_scoped_to_the_authenticated_user():
    use_case = _FakeUseCase(output=[])
    client = _client(get_list_tracked_applications_use_case, use_case)

    client.get("/api/tracked-applications?limit=25")

    assert use_case.received.user_id == "user-123"
    assert use_case.received.limit == 25


def test_an_out_of_range_limit_is_refused_before_the_use_case_runs():
    use_case = _FakeUseCase(output=[])
    client = _client(get_list_tracked_applications_use_case, use_case)

    assert client.get("/api/tracked-applications?limit=0").status_code == 422
    assert client.get("/api/tracked-applications?limit=501").status_code == 422
    assert use_case.received is None


# ---- updating a status -------------------------------------------------------


def test_a_status_change_returns_the_updated_record():
    updated = _application(
        status="interviewing",
        allowed_next_statuses=["offer", "rejected", "withdrawn"],
    )
    use_case = _FakeUseCase(output=updated)
    client = _client(get_update_tracked_application_status_use_case, use_case)

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "interviewing"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "interviewing"
    # And the next set of choices, so the control that made the change
    # re-renders from what was stored rather than from what it assumed.
    assert body["allowed_next_statuses"] == ["offer", "rejected", "withdrawn"]


def test_the_update_is_scoped_to_the_authenticated_user():
    use_case = _FakeUseCase(output=_application())
    client = _client(get_update_tracked_application_status_use_case, use_case)

    client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "interviewing"}
    )

    assert use_case.received.user_id == "user-123"
    assert use_case.received.application_id == "app-1"
    assert use_case.received.status == "interviewing"


def test_a_terminal_application_reports_no_further_choices():
    use_case = _FakeUseCase(
        output=_application(status="rejected", is_open=False, allowed_next_statuses=[])
    )
    client = _client(get_update_tracked_application_status_use_case, use_case)

    body = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "rejected"}
    ).json()

    assert body["is_open"] is False
    assert body["allowed_next_statuses"] == []


def test_an_unknown_application_is_404():
    use_case = _FakeUseCase(error=TrackedApplicationNotFoundError("app-nope"))
    client = _client(get_update_tracked_application_status_use_case, use_case)

    response = client.patch(
        "/api/tracked-applications/app-nope/status", json={"status": "offer"}
    )

    assert response.status_code == 404


def test_a_value_that_is_not_a_status_is_422():
    use_case = _FakeUseCase(error=InvalidValueError("'ghosted' is not a status."))
    client = _client(get_update_tracked_application_status_use_case, use_case)

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "ghosted"}
    )

    assert response.status_code == 422


def test_a_transition_the_lifecycle_forbids_is_409():
    """Well-formed, and refused as things stand — the distinction between
    "that is not a status" and "you cannot go there from here"."""
    use_case = _FakeUseCase(
        error=BusinessRuleViolationError(
            "Cannot move application from 'rejected' to 'interviewing'."
        )
    )
    client = _client(get_update_tracked_application_status_use_case, use_case)

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": "interviewing"}
    )

    assert response.status_code == 409
    assert "rejected" in response.json()["detail"]


def test_an_empty_status_is_refused_before_the_use_case_runs():
    use_case = _FakeUseCase(output=_application())
    client = _client(get_update_tracked_application_status_use_case, use_case)

    response = client.patch(
        "/api/tracked-applications/app-1/status", json={"status": ""}
    )

    assert response.status_code == 422
    assert use_case.received is None


def test_there_is_no_route_that_creates_or_deletes_a_tracked_application():
    """A record exists because an application was sent, and erasing history is
    Epic 07's user-scoped purge — neither is something a request can reach."""
    use_case = _FakeUseCase(output=[])
    client = _client(get_list_tracked_applications_use_case, use_case)

    # 405: the collection exists, but only to be read.
    assert client.post("/api/tracked-applications", json={}).status_code == 405
    # 404: there is no single-application resource at all — the only route
    # under an id is the status sub-resource, so there is nothing to delete.
    assert client.delete("/api/tracked-applications/app-1").status_code == 404
    assert client.delete("/api/tracked-applications/app-1/status").status_code == 405
