"""Tests for the document-revision route: auth gating, what it forwards to
the use case, and how each outcome maps to a status code.

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
    DocumentVersionConflictError,
    UnattestedGenerationError,
)
from src.domain.exceptions import (
    InvalidValueError,
    JobPostingNotFoundError,
    ProfileNotFoundError,
)
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_current_user,
    get_revise_generated_document_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_URL = "/api/job-postings/job-1/documents/tailored_resume/revisions"
_EDIT = "Backend Engineer, Acme Corp\nBuilt payment services in Python."


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
        "document_id": "doc-2",
        "job_posting_id": "job-1",
        "document_kind": "tailored_resume",
        "content": _EDIT,
        "version": 2,
        "backing_sources": ["parsed_resume"],
        "violations": [],
    }
    defaults.update(overrides)
    return GuardedDocumentOutput(**defaults)


def _client(use_case) -> tuple[TestClient, object]:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_revise_generated_document_use_case] = lambda: use_case
    return TestClient(app), app


def test_without_an_authorization_header_the_route_is_rejected():
    response = TestClient(create_app()).post(_URL, json={"content": _EDIT})

    assert response.status_code == 401


def test_a_stored_edit_comes_back_as_the_next_version():
    client, app = _client(_FakeUseCase(output=_output()))

    response = client.post(_URL, json={"content": _EDIT})

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == _EDIT
    assert body["version"] == 2
    assert body["document_kind"] == "tailored_resume"
    app.dependency_overrides.clear()


def test_the_edit_is_stored_for_the_authenticated_caller_and_the_path_document():
    use_case = _FakeUseCase(output=_output())
    client, app = _client(use_case)

    client.post(_URL, json={"content": _EDIT})

    assert use_case.received.user_id == "user-123"
    assert use_case.received.job_posting_id == "job-1"
    assert use_case.received.document_kind == "tailored_resume"
    assert use_case.received.content == _EDIT
    app.dependency_overrides.clear()


def test_lines_the_guard_removed_from_the_edit_are_reported_with_the_stored_version():
    """A candidate's own sentence is held to the same provenance rule as a
    model's, and the response says which lines did not survive."""
    client, app = _client(
        _FakeUseCase(
            output=_output(
                violations=[
                    ProvenanceViolationOutput(
                        line="Expert in Terraform.",
                        unsupported_terms=["terraform"],
                    )
                ]
            )
        )
    )

    response = client.post(_URL, json={"content": f"{_EDIT}\nExpert in Terraform."})

    assert response.status_code == 201
    assert response.json()["violations"][0]["unsupported_terms"] == ["terraform"]
    app.dependency_overrides.clear()


def test_an_empty_edit_is_rejected_before_it_reaches_the_use_case():
    use_case = _FakeUseCase(output=_output())
    client, app = _client(use_case)

    response = client.post(_URL, json={"content": ""})

    assert response.status_code == 422
    assert use_case.received is None
    app.dependency_overrides.clear()


def test_an_unknown_document_kind_is_a_422():
    client, app = _client(
        _FakeUseCase(error=InvalidValueError("'notes' is not a kind of document."))
    )

    response = client.post(
        "/api/job-postings/job-1/documents/notes/revisions", json={"content": _EDIT}
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_an_edit_with_nothing_attested_left_is_a_422():
    client, app = _client(
        _FakeUseCase(
            error=UnattestedGenerationError(
                document_kind="tailored_resume", unsupported_terms=("terraform",)
            )
        )
    )

    response = client.post(_URL, json={"content": "Expert in Terraform."})

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_an_unknown_posting_is_a_404():
    client, app = _client(_FakeUseCase(error=JobPostingNotFoundError("job-1")))

    assert client.post(_URL, json={"content": _EDIT}).status_code == 404
    app.dependency_overrides.clear()


def test_a_candidate_without_a_profile_is_a_404():
    client, app = _client(_FakeUseCase(error=ProfileNotFoundError("user-123")))

    assert client.post(_URL, json={"content": _EDIT}).status_code == 404
    app.dependency_overrides.clear()


def test_a_concurrent_write_claiming_the_same_version_is_a_409():
    client, app = _client(
        _FakeUseCase(
            error=DocumentVersionConflictError(
                job_posting_id="job-1", document_kind="tailored_resume", version=2
            )
        )
    )

    assert client.post(_URL, json={"content": _EDIT}).status_code == 409
    app.dependency_overrides.clear()
