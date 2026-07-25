"""Tests for the tailored-resume route: auth gating, the guarded document
it serializes, and how each pipeline outcome maps to a status code.

Uses FastAPI's dependency_overrides with an in-memory fake use case, so no
real database or LLM call is required.
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
    get_generate_tailored_resume_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_URL = "/api/job-postings/job-1/tailored-resume"


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
        "document_kind": "tailored_resume",
        "content": "EXPERIENCE\nBackend Engineer at Acme Corp",
        "backing_sources": ["parsed_resume"],
        "violations": [],
    }
    defaults.update(overrides)
    return GuardedDocumentOutput(**defaults)


def _client(use_case) -> tuple[TestClient, object]:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_generate_tailored_resume_use_case] = lambda: use_case
    return TestClient(app), app


def test_without_an_authorization_header_the_route_is_rejected():
    response = TestClient(create_app()).post(_URL)

    assert response.status_code == 401


def test_a_generated_resume_comes_back_with_its_provenance():
    use_case = _FakeUseCase(output=_output())
    client, app = _client(use_case)

    response = client.post(_URL)

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "EXPERIENCE\nBackend Engineer at Acme Corp"
    assert body["document_kind"] == "tailored_resume"
    assert body["backing_sources"] == ["parsed_resume"]
    assert body["violations"] == []
    app.dependency_overrides.clear()


def test_the_resume_is_generated_for_the_authenticated_caller_and_the_path_posting():
    use_case = _FakeUseCase(output=_output())
    client, app = _client(use_case)

    client.post(_URL)

    assert use_case.received.user_id == "user-123"
    assert use_case.received.job_posting_id == "job-1"
    app.dependency_overrides.clear()


def test_stripped_lines_are_reported_alongside_a_successful_resume():
    """Violations are a diagnostic, not a failure: what came back is still
    made only of attested claims."""
    use_case = _FakeUseCase(
        output=_output(
            violations=[
                ProvenanceViolationOutput(
                    line="Staff Engineer at Initech",
                    unsupported_terms=["staff", "initech"],
                )
            ]
        )
    )
    client, app = _client(use_case)

    response = client.post(_URL)

    assert response.status_code == 201
    assert response.json()["violations"] == [
        {
            "line": "Staff Engineer at Initech",
            "unsupported_terms": ["staff", "initech"],
        }
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


def test_nothing_attested_surviving_is_a_422_that_explains_itself():
    client, app = _client(
        _FakeUseCase(
            error=UnattestedGenerationError(
                document_kind="tailored_resume",
                unsupported_terms=("initech", "phd"),
            )
        )
    )

    response = client.post(_URL)

    assert response.status_code == 422
    assert "initech" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_an_llm_failure_is_a_502():
    client, app = _client(_FakeUseCase(error=ExternalServiceError("boom")))

    assert client.post(_URL).status_code == 502
    app.dependency_overrides.clear()
