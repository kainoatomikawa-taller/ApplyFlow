"""Tests for the job-postings router: auth gating and the ranked-matches
endpoint's happy path / not-found path.

Uses FastAPI's dependency_overrides with an in-memory fake use case, so
no real database or LLM call is required.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.job_posting_dtos import JobPostingOutput
from src.application.dtos.ranked_job_dtos import RankedJobOutput
from src.domain.exceptions import ProfileNotFoundError
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_current_user,
    get_rank_matched_jobs_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")

_RANKED = RankedJobOutput(
    job_posting=JobPostingOutput(
        id="job-1",
        source="adzuna",
        company="Acme Corp",
        title="Backend Engineer",
        apply_url="https://acme.example.com/careers/1",
        location="Remote",
        is_remote=True,
        status="active",
        posted_at=None,
        created_at=datetime(2026, 1, 1),
        requirements=None,
    ),
    score=80,
    rationale="Strong match on Python experience.",
    gaps=["Kubernetes"],
)


class _FakeRankUseCase:
    def __init__(self, outputs=None, error=None) -> None:
        self._outputs = outputs
        self._error = error

    async def execute(self, dto):
        if self._error is not None:
            raise self._error
        return self._outputs


def _client(app) -> TestClient:
    return TestClient(app)


def test_list_matches_without_authorization_header_is_rejected():
    client = _client(create_app())
    response = client.get("/api/job-postings/matches")
    assert response.status_code == 401


def test_list_matches_happy_path_returns_ranked_list():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_rank_matched_jobs_use_case] = (
        lambda: _FakeRankUseCase(outputs=[_RANKED])
    )

    response = _client(app).get("/api/job-postings/matches")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["job_posting"]["id"] == "job-1"
    assert body[0]["score"] == 80
    assert body[0]["rationale"] == "Strong match on Python experience."
    assert body[0]["gaps"] == ["Kubernetes"]
    app.dependency_overrides.clear()


def test_list_matches_returns_empty_list_when_nothing_qualifies():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_rank_matched_jobs_use_case] = (
        lambda: _FakeRankUseCase(outputs=[])
    )

    response = _client(app).get("/api/job-postings/matches")

    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


def test_list_matches_returns_404_when_profile_does_not_exist():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_rank_matched_jobs_use_case] = (
        lambda: _FakeRankUseCase(error=ProfileNotFoundError("user-123"))
    )

    response = _client(app).get("/api/job-postings/matches")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_list_matches_respects_limit_query_param_bounds():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_rank_matched_jobs_use_case] = (
        lambda: _FakeRankUseCase(outputs=[])
    )

    response = _client(app).get("/api/job-postings/matches?limit=0")

    assert response.status_code == 422
    app.dependency_overrides.clear()
