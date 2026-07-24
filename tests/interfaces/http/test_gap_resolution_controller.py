"""Tests for the gap-resolution router: auth gating, question generation,
and answer resolution (captured vs. cleanly-omitted decline).

Uses FastAPI's dependency_overrides with in-memory fake use cases, so no
real database or LLM call is required.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.gap_resolution_dtos import (
    GapResolutionQuestionOutput,
    ResolveGapAnswerOutput,
)
from src.application.exceptions import ExternalServiceError
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_current_user,
    get_generate_gap_resolution_questions_use_case,
    get_resolve_gap_answer_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")


class _FakeQuestionsUseCase:
    def __init__(self, outputs=None, error=None) -> None:
        self._outputs = outputs
        self._error = error

    async def execute(self, dto):
        if self._error is not None:
            raise self._error
        return self._outputs


class _FakeResolveUseCase:
    def __init__(self, output=None, error=None) -> None:
        self._output = output
        self._error = error

    async def execute(self, dto):
        if self._error is not None:
            raise self._error
        return self._output


def _client(app) -> TestClient:
    return TestClient(app)


def test_generate_questions_without_authorization_header_is_rejected():
    client = _client(create_app())
    response = client.post(
        "/api/gap-resolution/questions", json={"gaps": ["Kubernetes"]}
    )
    assert response.status_code == 401


def test_generate_questions_happy_path_returns_one_question_per_gap():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_generate_gap_resolution_questions_use_case] = lambda: (
        _FakeQuestionsUseCase(
            outputs=[
                GapResolutionQuestionOutput(
                    gap="Kubernetes",
                    question="Have you worked with Kubernetes or similar tools?",
                ),
                GapResolutionQuestionOutput(
                    gap="Leadership experience",
                    question="Have you ever led a team or mentored someone?",
                ),
            ]
        )
    )

    response = _client(app).post(
        "/api/gap-resolution/questions",
        json={"gaps": ["Kubernetes", "Leadership experience"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["gap"] == "Kubernetes"
    assert "Kubernetes" in body[0]["question"]
    app.dependency_overrides.clear()


def test_generate_questions_returns_502_when_the_llm_call_fails():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_generate_gap_resolution_questions_use_case] = lambda: (
        _FakeQuestionsUseCase(error=ExternalServiceError("boom"))
    )

    response = _client(app).post(
        "/api/gap-resolution/questions", json={"gaps": ["Kubernetes"]}
    )

    assert response.status_code == 502
    app.dependency_overrides.clear()


def test_resolve_answer_without_authorization_header_is_rejected():
    client = _client(create_app())
    response = client.post(
        "/api/gap-resolution/answers",
        json={
            "gap": "Kubernetes",
            "question": "Have you used Kubernetes?",
            "answer": "",
        },
    )
    assert response.status_code == 401


def test_resolve_answer_captures_a_genuine_response():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_resolve_gap_answer_use_case] = lambda: (
        _FakeResolveUseCase(
            output=ResolveGapAnswerOutput(
                gap="Kubernetes", captured=True, answer_memory_id="mem-1"
            )
        )
    )

    response = _client(app).post(
        "/api/gap-resolution/answers",
        json={
            "gap": "Kubernetes",
            "question": "Have you used Kubernetes or similar tools?",
            "answer": "Yes, ran it in production for two years.",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "gap": "Kubernetes",
        "captured": True,
        "answer_memory_id": "mem-1",
    }
    app.dependency_overrides.clear()


def test_resolve_answer_cleanly_omits_a_decline():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_resolve_gap_answer_use_case] = lambda: (
        _FakeResolveUseCase(
            output=ResolveGapAnswerOutput(gap="Kubernetes", captured=False)
        )
    )

    response = _client(app).post(
        "/api/gap-resolution/answers",
        json={
            "gap": "Kubernetes",
            "question": "Have you used Kubernetes or similar tools?",
            "answer": "nothing to add",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "gap": "Kubernetes",
        "captured": False,
        "answer_memory_id": None,
    }
    app.dependency_overrides.clear()


def test_resolve_answer_returns_502_when_the_embedding_call_fails():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_resolve_gap_answer_use_case] = lambda: (
        _FakeResolveUseCase(error=ExternalServiceError("boom"))
    )

    response = _client(app).post(
        "/api/gap-resolution/answers",
        json={
            "gap": "Kubernetes",
            "question": "Have you used Kubernetes?",
            "answer": "Yes.",
        },
    )

    assert response.status_code == 502
    app.dependency_overrides.clear()
