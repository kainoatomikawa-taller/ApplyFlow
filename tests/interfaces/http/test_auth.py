"""Tests proving the applications router is gated behind authentication.

Uses FastAPI's dependency_overrides so no real database or Supabase
project is required to prove the wiring is correct.
"""

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import get_current_user, get_list_use_case


class _FakeListUseCase:
    def __init__(self) -> None:
        self.called_with: list[str] = []

    async def execute(self, candidate_email: str) -> list:
        self.called_with.append(candidate_email)
        return []


def _client() -> TestClient:
    return TestClient(create_app())


def test_request_without_authorization_header_is_rejected():
    client = _client()
    response = client.get("/api/applications")
    assert response.status_code == 401


def test_request_with_malformed_authorization_header_is_rejected():
    client = _client()
    response = client.get(
        "/api/applications",
        headers={"Authorization": "not-a-bearer-token"},
    )
    assert response.status_code == 401


def test_request_with_an_invalid_token_is_rejected():
    client = _client()
    response = client.get(
        "/api/applications",
        headers={"Authorization": "Bearer garbage.token.value"},
    )
    assert response.status_code == 401


def test_authenticated_request_reaches_the_use_case():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUserDTO(
        subject="user-123", email="dev@example.com"
    )
    fake = _FakeListUseCase()
    app.dependency_overrides[get_list_use_case] = lambda: fake

    client = TestClient(app)
    response = client.get("/api/applications")
    assert response.status_code == 200
    assert response.json() == []
    # The candidate came from the token, not from the URL — see
    # `application_controller.list_applications` for why that matters.
    assert fake.called_with == ["dev@example.com"]

    app.dependency_overrides.clear()


def test_a_candidate_email_query_parameter_is_ignored_rather_than_honoured():
    """A stale client (or a probe) sending `?candidate_email=` must not be able
    to steer the query. FastAPI drops unexpected query params, so the check
    that matters is which email reached the use case."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUserDTO(
        subject="user-123", email="dev@example.com"
    )
    fake = _FakeListUseCase()
    app.dependency_overrides[get_list_use_case] = lambda: fake

    client = TestClient(app)
    response = client.get(
        "/api/applications", params={"candidate_email": "someone.else@example.com"}
    )
    assert response.status_code == 200
    assert fake.called_with == ["dev@example.com"]

    app.dependency_overrides.clear()


def test_a_token_without_an_email_claim_is_a_client_error():
    """Rather than an empty list, which would look like "no applications yet"
    and hide a misconfigured auth provider."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUserDTO(
        subject="user-123", email=None
    )
    fake = _FakeListUseCase()
    app.dependency_overrides[get_list_use_case] = lambda: fake

    client = TestClient(app)
    response = client.get("/api/applications")
    assert response.status_code == 400
    assert fake.called_with == []

    app.dependency_overrides.clear()
