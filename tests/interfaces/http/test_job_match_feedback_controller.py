"""Tests for the job-match-feedback router: auth gating, submit happy
path + error paths, listing, and the scoring-feedback analysis endpoint.

Uses FastAPI's dependency_overrides with in-memory fakes, so no real
database is required.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.job_match_feedback_dtos import (
    JobMatchFeedbackOutput,
    ScoreBucketAgreementOutput,
    ScoringFeedbackSummaryOutput,
)
from src.domain.exceptions import InvalidValueError, JobPostingNotFoundError
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_analyze_scoring_feedback_use_case,
    get_current_user,
    get_list_job_match_feedback_use_case,
    get_submit_job_match_feedback_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")

_FEEDBACK_OUTPUT = JobMatchFeedbackOutput(
    id="feedback-1",
    user_id="user-123",
    job_posting_id="job-1",
    rating="thumbs_up",
    score_at_feedback=85,
    created_at=datetime(2026, 1, 1),
)


class _FakeSubmitUseCase:
    def __init__(self, output=None, error=None) -> None:
        self._output = output
        self._error = error

    async def execute(self, dto):
        if self._error is not None:
            raise self._error
        return self._output


class _FakeListUseCase:
    def __init__(self, outputs) -> None:
        self._outputs = outputs

    async def execute(self, user_id, *, limit=100):
        return self._outputs


class _FakeAnalyzeUseCase:
    def __init__(self, output) -> None:
        self._output = output

    async def execute(self, *, limit=1000):
        return self._output


def _client(app) -> TestClient:
    return TestClient(app)


def test_submit_feedback_without_authorization_header_is_rejected():
    client = _client(create_app())
    response = client.post(
        "/api/job-postings/job-1/feedback",
        json={"rating": "thumbs_up", "score_at_feedback": 85},
    )
    assert response.status_code == 401


def test_submit_feedback_happy_path_returns_201():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_submit_job_match_feedback_use_case] = (
        lambda: _FakeSubmitUseCase(output=_FEEDBACK_OUTPUT)
    )

    response = _client(app).post(
        "/api/job-postings/job-1/feedback",
        json={"rating": "thumbs_up", "score_at_feedback": 85},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "feedback-1"
    assert body["rating"] == "thumbs_up"
    assert body["score_at_feedback"] == 85
    app.dependency_overrides.clear()


def test_submit_feedback_rejects_an_invalid_rating_value():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_submit_job_match_feedback_use_case] = (
        lambda: _FakeSubmitUseCase(output=_FEEDBACK_OUTPUT)
    )

    response = _client(app).post(
        "/api/job-postings/job-1/feedback",
        json={"rating": "meh", "score_at_feedback": 85},
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_submit_feedback_rejects_an_out_of_range_score():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_submit_job_match_feedback_use_case] = (
        lambda: _FakeSubmitUseCase(output=_FEEDBACK_OUTPUT)
    )

    response = _client(app).post(
        "/api/job-postings/job-1/feedback",
        json={"rating": "thumbs_up", "score_at_feedback": 150},
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_submit_feedback_returns_404_for_unknown_job_posting():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_submit_job_match_feedback_use_case] = (
        lambda: _FakeSubmitUseCase(error=JobPostingNotFoundError("does-not-exist"))
    )

    response = _client(app).post(
        "/api/job-postings/does-not-exist/feedback",
        json={"rating": "thumbs_up", "score_at_feedback": 85},
    )

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_submit_feedback_returns_422_when_the_use_case_rejects_the_rating():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_submit_job_match_feedback_use_case] = (
        lambda: _FakeSubmitUseCase(error=InvalidValueError("bad rating"))
    )

    response = _client(app).post(
        "/api/job-postings/job-1/feedback",
        json={"rating": "thumbs_up", "score_at_feedback": 85},
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_list_feedback_returns_the_current_users_history():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_list_job_match_feedback_use_case] = (
        lambda: _FakeListUseCase([_FEEDBACK_OUTPUT])
    )

    response = _client(app).get("/api/job-postings/feedback")

    assert response.status_code == 200
    assert len(response.json()) == 1
    app.dependency_overrides.clear()


def test_scoring_feedback_analysis_returns_bucketed_summary():
    summary = ScoringFeedbackSummaryOutput(
        buckets=[
            ScoreBucketAgreementOutput(
                range_start=80,
                range_end=100,
                thumbs_up=8,
                thumbs_down=2,
                agreement_rate=0.8,
            )
        ]
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_analyze_scoring_feedback_use_case] = (
        lambda: _FakeAnalyzeUseCase(summary)
    )

    response = _client(app).get("/api/job-postings/feedback/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["buckets"][0]["range_start"] == 80
    assert body["buckets"][0]["agreement_rate"] == 0.8
    app.dependency_overrides.clear()
