"""Tests proving the applications router is gated behind authentication.

Uses FastAPI's dependency_overrides so no real database or Supabase
project is required to prove the wiring is correct.
"""

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import get_current_user, get_list_use_case


class _FakeListUseCase:
    async def execute(self, candidate_email: str) -> list:
        return []


def _client() -> TestClient:
    return TestClient(create_app())


def test_request_without_authorization_header_is_rejected():
    client = _client()
    response = client.get("/api/applications", params={"candidate_email": "a@b.com"})
    assert response.status_code == 401


def test_request_with_malformed_authorization_header_is_rejected():
    client = _client()
    response = client.get(
        "/api/applications",
        params={"candidate_email": "a@b.com"},
        headers={"Authorization": "not-a-bearer-token"},
    )
    assert response.status_code == 401


def test_request_with_an_invalid_token_is_rejected():
    client = _client()
    response = client.get(
        "/api/applications",
        params={"candidate_email": "a@b.com"},
        headers={"Authorization": "Bearer garbage.token.value"},
    )
    assert response.status_code == 401


def test_authenticated_request_reaches_the_use_case():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUserDTO(
        subject="user-123", email="dev@example.com"
    )
    app.dependency_overrides[get_list_use_case] = lambda: _FakeListUseCase()

    client = TestClient(app)
    response = client.get("/api/applications", params={"candidate_email": "a@b.com"})
    assert response.status_code == 200
    assert response.json() == []

    app.dependency_overrides.clear()
