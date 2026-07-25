"""Tests for the portal routes: auth gating, what each response serializes,
and how each failure maps to a status code.

The status-code choices carry the design, so they are what is asserted:
handing off is a **200** (nothing failed — ApplyFlow did the right thing and
stopped), an unreachable portal is a 502, a hand-off that is not this
candidate's is a 404 rather than a 403, and resolving one twice is a 409.

Uses FastAPI's dependency_overrides with in-memory fake use cases, so no real
database or browser is required.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.portal_handoff_dtos import (
    HardStopOutput,
    InspectApplicationPortalOutput,
    ListPortalHandoffsOutput,
    PortalFieldOutput,
    PortalHandoffOutput,
)
from src.application.exceptions import BrowserAutomationError, BrowserNavigationError
from src.domain.exceptions import (
    BusinessRuleViolationError,
    JobPostingNotFoundError,
    PortalHandoffNotFoundError,
)
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_abandon_portal_handoff_use_case,
    get_current_user,
    get_inspect_application_portal_use_case,
    get_list_portal_handoffs_use_case,
    get_resume_portal_handoff_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_DETECTED_AT = datetime(2026, 7, 25, 9, 0, tzinfo=UTC)
_APPLY_URL = "https://globex.example.com/apply/4242"
_PAUSED_URL = "https://globex.example.com/login?next=/apply/4242"


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


def _handoff_output(**overrides) -> PortalHandoffOutput:
    defaults = {
        "id": "handoff-1",
        "job_posting_id": "job-1",
        "apply_url": _APPLY_URL,
        "paused_url": _PAUSED_URL,
        "status": "awaiting_user",
        "is_open": True,
        "created_at": _DETECTED_AT,
        "last_detected_at": _DETECTED_AT,
        "hard_stops": [
            HardStopOutput(
                kind="account_wall",
                refusal_reason="This portal wants credentials.",
                human_action="Open the portal yourself and sign in.",
                evidence=["the form presents 1 password field"],
            )
        ],
    }
    defaults.update(overrides)
    return PortalHandoffOutput(**defaults)


def _client(dependency, use_case) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[dependency] = lambda: use_case
    return TestClient(app)


# ---- auth -------------------------------------------------------------------


def test_every_portal_route_requires_authentication():
    client = TestClient(create_app())

    assert client.get("/api/portal/handoffs").status_code == 401
    assert (
        client.post("/api/portal/inspections", json={"job_posting_id": "job-1"})
    ).status_code == 401
    assert (
        client.post("/api/portal/handoffs/handoff-1/resume", json={})
    ).status_code == 401
    assert (
        client.post("/api/portal/handoffs/handoff-1/abandon", json={})
    ).status_code == 401


# ---- inspecting a portal ----------------------------------------------------


def test_a_clean_portal_returns_its_questions():
    use_case = _FakeUseCase(
        output=InspectApplicationPortalOutput(
            job_posting_id="job-1",
            apply_url=_APPLY_URL,
            landed_url=_APPLY_URL,
            is_handed_off=False,
            fields=[
                PortalFieldOutput(
                    label="Full name", kind="text", name="full_name", required=True
                )
            ],
        )
    )
    client = _client(get_inspect_application_portal_use_case, use_case)

    response = client.post("/api/portal/inspections", json={"job_posting_id": "job-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["is_handed_off"] is False
    assert body["handoff"] is None
    assert body["fields"] == [
        {
            "label": "Full name",
            "kind": "text",
            "name": "full_name",
            "required": True,
            "human_only_boundary": None,
        }
    ]


def test_handing_off_is_a_200_with_the_hand_off_and_no_fields():
    """Nothing failed: ApplyFlow stopped where it should. Reporting that as an
    error would push clients into retrying a correct outcome — and the empty
    field list is the pause itself, not a detail."""
    use_case = _FakeUseCase(
        output=InspectApplicationPortalOutput(
            job_posting_id="job-1",
            apply_url=_APPLY_URL,
            landed_url=_PAUSED_URL,
            is_handed_off=True,
            handoff=_handoff_output(),
            fields=[],
        )
    )
    client = _client(get_inspect_application_portal_use_case, use_case)

    response = client.post("/api/portal/inspections", json={"job_posting_id": "job-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["is_handed_off"] is True
    assert body["fields"] == []
    assert body["landed_url"] == _PAUSED_URL
    handoff = body["handoff"]
    assert handoff["status"] == "awaiting_user"
    assert handoff["is_open"] is True
    assert handoff["paused_url"] == _PAUSED_URL
    assert handoff["hard_stops"][0]["kind"] == "account_wall"
    assert handoff["hard_stops"][0]["human_action"]
    assert handoff["hard_stops"][0]["evidence"] == [
        "the form presents 1 password field"
    ]


def test_a_cleared_hand_off_is_reported_on_a_clean_inspection():
    use_case = _FakeUseCase(
        output=InspectApplicationPortalOutput(
            job_posting_id="job-1",
            apply_url=_APPLY_URL,
            landed_url=_APPLY_URL,
            is_handed_off=False,
            cleared_handoff_id="handoff-1",
        )
    )
    client = _client(get_inspect_application_portal_use_case, use_case)

    body = client.post(
        "/api/portal/inspections", json={"job_posting_id": "job-1"}
    ).json()

    assert body["cleared_handoff_id"] == "handoff-1"


def test_the_inspection_is_scoped_to_the_authenticated_user():
    """The user id comes from the token, never from the request body."""
    use_case = _FakeUseCase(
        output=InspectApplicationPortalOutput(
            job_posting_id="job-1",
            apply_url=_APPLY_URL,
            landed_url=_APPLY_URL,
            is_handed_off=False,
        )
    )
    client = _client(get_inspect_application_portal_use_case, use_case)

    client.post("/api/portal/inspections", json={"job_posting_id": "job-1"})

    assert use_case.received.user_id == "user-123"
    assert use_case.received.job_posting_id == "job-1"


def test_an_unknown_posting_is_a_404():
    use_case = _FakeUseCase(error=JobPostingNotFoundError("job-9"))
    client = _client(get_inspect_application_portal_use_case, use_case)

    response = client.post("/api/portal/inspections", json={"job_posting_id": "job-9"})

    assert response.status_code == 404


def test_a_portal_that_cannot_be_loaded_is_a_502():
    use_case = _FakeUseCase(
        error=BrowserNavigationError(_APPLY_URL, "it did not load within 30s")
    )
    client = _client(get_inspect_application_portal_use_case, use_case)

    response = client.post("/api/portal/inspections", json={"job_posting_id": "job-1"})

    assert response.status_code == 502


def test_a_browser_that_cannot_run_is_a_500():
    """Ours to fix, not the portal's — a missing Chromium build is not an
    upstream failure."""
    use_case = _FakeUseCase(
        error=BrowserAutomationError("Could not launch Chromium for portal automation.")
    )
    client = _client(get_inspect_application_portal_use_case, use_case)

    response = client.post("/api/portal/inspections", json={"job_posting_id": "job-1"})

    assert response.status_code == 500


def test_an_inspection_without_a_posting_id_is_rejected():
    use_case = _FakeUseCase(output=None)
    client = _client(get_inspect_application_portal_use_case, use_case)

    assert client.post("/api/portal/inspections", json={}).status_code == 422
    assert (
        client.post("/api/portal/inspections", json={"job_posting_id": ""}).status_code
        == 422
    )


# ---- listing hand-offs ------------------------------------------------------


def test_the_hand_off_list_reports_what_is_still_waiting():
    use_case = _FakeUseCase(
        output=ListPortalHandoffsOutput(
            handoffs=[
                _handoff_output(),
                _handoff_output(
                    id="handoff-0",
                    status="resumed",
                    is_open=False,
                    resolved_at=_DETECTED_AT,
                    resolution_note="Signed in as me",
                ),
            ],
            open_count=1,
        )
    )
    client = _client(get_list_portal_handoffs_use_case, use_case)

    response = client.get("/api/portal/handoffs")

    assert response.status_code == 200
    body = response.json()
    assert body["open_count"] == 1
    assert [item["id"] for item in body["handoffs"]] == ["handoff-1", "handoff-0"]
    assert body["handoffs"][1]["resolution_note"] == "Signed in as me"


def test_the_list_passes_through_its_filters():
    use_case = _FakeUseCase(output=ListPortalHandoffsOutput())
    client = _client(get_list_portal_handoffs_use_case, use_case)

    client.get("/api/portal/handoffs?open_only=true&limit=10")

    assert use_case.received.open_only is True
    assert use_case.received.limit == 10
    assert use_case.received.user_id == "user-123"


def test_an_out_of_range_limit_is_rejected():
    use_case = _FakeUseCase(output=ListPortalHandoffsOutput())
    client = _client(get_list_portal_handoffs_use_case, use_case)

    assert client.get("/api/portal/handoffs?limit=0").status_code == 422
    assert client.get("/api/portal/handoffs?limit=5000").status_code == 422


# ---- resolving a hand-off ---------------------------------------------------


def test_resuming_returns_the_closed_hand_off():
    use_case = _FakeUseCase(
        output=_handoff_output(
            status="resumed",
            is_open=False,
            resolved_at=_DETECTED_AT,
            resolution_note="Solved the captcha",
        )
    )
    client = _client(get_resume_portal_handoff_use_case, use_case)

    response = client.post(
        "/api/portal/handoffs/handoff-1/resume", json={"note": "Solved the captcha"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resumed"
    assert body["is_open"] is False
    assert body["resolution_note"] == "Solved the captcha"
    assert use_case.received.handoff_id == "handoff-1"
    assert use_case.received.user_id == "user-123"
    assert use_case.received.note == "Solved the captcha"


def test_resuming_without_a_note_is_allowed():
    use_case = _FakeUseCase(
        output=_handoff_output(
            status="resumed", is_open=False, resolved_at=_DETECTED_AT
        )
    )
    client = _client(get_resume_portal_handoff_use_case, use_case)

    assert (
        client.post("/api/portal/handoffs/handoff-1/resume", json={}).status_code == 200
    )
    assert use_case.received.note == ""


def test_abandoning_returns_the_closed_hand_off():
    use_case = _FakeUseCase(
        output=_handoff_output(
            status="abandoned",
            is_open=False,
            resolved_at=_DETECTED_AT,
            resolution_note="Applying by hand",
        )
    )
    client = _client(get_abandon_portal_handoff_use_case, use_case)

    response = client.post(
        "/api/portal/handoffs/handoff-1/abandon", json={"note": "Applying by hand"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "abandoned"


def test_someone_elses_hand_off_is_a_404_not_a_403():
    """A 403 would confirm the id exists."""
    use_case = _FakeUseCase(error=PortalHandoffNotFoundError("handoff-9"))
    client = _client(get_resume_portal_handoff_use_case, use_case)

    response = client.post("/api/portal/handoffs/handoff-9/resume", json={})

    assert response.status_code == 404


def test_resolving_a_hand_off_twice_is_a_409():
    use_case = _FakeUseCase(
        error=BusinessRuleViolationError(
            "Cannot move this hand-off from 'resumed' to 'resumed'; it was "
            "already resolved as 'resumed'."
        )
    )
    client = _client(get_resume_portal_handoff_use_case, use_case)

    response = client.post("/api/portal/handoffs/handoff-1/resume", json={})

    assert response.status_code == 409
    assert "already resolved" in response.json()["detail"]


def test_an_over_long_note_is_rejected_before_it_reaches_the_use_case():
    use_case = _FakeUseCase(output=_handoff_output())
    client = _client(get_resume_portal_handoff_use_case, use_case)

    response = client.post(
        "/api/portal/handoffs/handoff-1/resume", json={"note": "x" * 1001}
    )

    assert response.status_code == 422
    assert use_case.received is None
