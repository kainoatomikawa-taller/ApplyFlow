"""Tests for the cover-letter route: auth gating, the guarded document it
serializes, and how each pipeline outcome maps to a status code.

Uses FastAPI's dependency_overrides with an in-memory fake use case, so no
real database, embedding, or LLM call is required.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.generation_dtos import (
    GuardedDocumentOutput,
    ProvenanceViolationOutput,
)
from src.application.exceptions import (
    ExternalServiceError,
    UnattestedGenerationError,
)
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_current_user,
    get_generate_cover_letter_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_URL = "/api/job-postings/job-1/cover-letter"
_LETTER = (
    "Dear Hiring Manager,\n\nI led a team of 5 engineers.\n\nSincerely,\nDana Reyes"
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


def _output(**overrides) -> GuardedDocumentOutput:
    defaults = {
        "job_posting_id": "job-1",
        "document_kind": "cover_letter",
        "content": _LETTER,
        "backing_sources": ["answer"],
        "violations": [],
    }
    defaults.update(overrides)
    return GuardedDocumentOutput(**defaults)


def _client(use_case) -> tuple[TestClient, object]:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_generate_cover_letter_use_case] = lambda: use_case
    return TestClient(app), app


def test_without_an_authorization_header_the_route_is_rejected():
    response = TestClient(create_app()).post(_URL)

    assert response.status_code == 401


def test_a_generated_letter_comes_back_with_its_provenance():
    client, app = _client(_FakeUseCase(output=_output()))

    response = client.post(_URL)

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == _LETTER
    assert body["document_kind"] == "cover_letter"
    assert body["backing_sources"] == ["answer"]
    assert body["violations"] == []
    app.dependency_overrides.clear()


def test_the_letter_is_written_for_the_authenticated_caller_and_the_path_posting():
    use_case = _FakeUseCase(output=_output())
    client, app = _client(use_case)

    client.post(_URL)

    assert use_case.received.user_id == "user-123"
    assert use_case.received.job_posting_id == "job-1"
    app.dependency_overrides.clear()


def test_stripped_lines_are_reported_alongside_a_successful_letter():
    """Violations are a diagnostic, not a failure: what came back is still
    made only of attested claims."""
    client, app = _client(
        _FakeUseCase(
            output=_output(
                violations=[
                    ProvenanceViolationOutput(
                        line="I am a seasoned architect.",
                        unsupported_terms=["seasoned", "architect"],
                    )
                ]
            )
        )
    )

    response = client.post(_URL)

    assert response.status_code == 201
    assert response.json()["violations"][0]["unsupported_terms"] == [
        "seasoned",
        "architect",
    ]
    app.dependency_overrides.clear()


def test_an_unknown_posting_is_a_404():
    client, app = _client(_FakeUseCase(error=JobPostingNotFoundError("job-1")))

    assert client.post(_URL).status_code == 404
    app.dependency_overrides.clear()


def test_a_candidate_without_a_profile_is_a_404():
    client, app = _client(_FakeUseCase(error=ProfileNotFoundError("user-123")))

    assert client.post(_URL).status_code == 404
    app.dependency_overrides.clear()


def test_a_letter_with_nothing_attested_is_a_422_that_explains_itself():
    client, app = _client(
        _FakeUseCase(
            error=UnattestedGenerationError(
                document_kind="cover_letter",
                unsupported_terms=("seasoned", "expert"),
            )
        )
    )

    response = client.post(_URL)

    assert response.status_code == 422
    assert "seasoned" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_an_llm_or_embedding_failure_is_a_502():
    client, app = _client(_FakeUseCase(error=ExternalServiceError("boom")))

    assert client.post(_URL).status_code == 502
    app.dependency_overrides.clear()


def test_the_resume_route_is_untouched_by_the_letter_route():
    """Both live under /api/job-postings; each posting exposes both
    documents at distinct paths."""
    paths = create_app().openapi()["paths"]

    assert "/api/job-postings/{job_posting_id}/cover-letter" in paths
    assert "/api/job-postings/{job_posting_id}/tailored-resume" in paths
