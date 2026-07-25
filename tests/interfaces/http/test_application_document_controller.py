"""Tests for the application-document routes: auth gating, what each read
serializes, and how each failure maps to a status code.

Uses FastAPI's dependency_overrides with in-memory fake use cases, so no
real database is required.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.application.dtos.application_document_dtos import (
    ApplicationDocumentOutput,
    ApplicationDocumentSummaryOutput,
)
from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.domain.exceptions import (
    ApplicationDocumentNotFoundError,
    DocumentSnapshotIntegrityError,
    InvalidValueError,
    NoStoredApplicationDocumentError,
)
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_application_document_use_case,
    get_current_user,
    get_latest_application_document_use_case,
    get_list_application_documents_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_CREATED_AT = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)
_RESUME_TEXT = "EXPERIENCE\nBackend Engineer at Acme Corp (2019-2022)"


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


def _document_output(**overrides) -> ApplicationDocumentOutput:
    defaults = {
        "id": "doc-1",
        "job_posting_id": "job-1",
        "document_kind": "tailored_resume",
        "version": 2,
        "content": _RESUME_TEXT,
        "content_sha256": "a" * 64,
        "created_at": _CREATED_AT,
        "backing_sources": ["parsed_resume"],
    }
    defaults.update(overrides)
    return ApplicationDocumentOutput(**defaults)


def _summary_output(**overrides) -> ApplicationDocumentSummaryOutput:
    defaults = {
        "id": "doc-1",
        "job_posting_id": "job-1",
        "document_kind": "cover_letter",
        "version": 1,
        "content_sha256": "b" * 64,
        "created_at": _CREATED_AT,
        "backing_sources": ["answer"],
    }
    defaults.update(overrides)
    return ApplicationDocumentSummaryOutput(**defaults)


def _client(dependency, use_case) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[dependency] = lambda: use_case
    return TestClient(app)


# ---- auth -------------------------------------------------------------------


def test_every_document_route_requires_authentication():
    client = TestClient(create_app())

    for url in (
        "/api/application-documents",
        "/api/application-documents/doc-1",
        "/api/job-postings/job-1/documents",
        "/api/job-postings/job-1/documents/cover_letter/latest",
    ):
        assert client.get(url).status_code == 401, url


# ---- reading one document ---------------------------------------------------


def test_a_stored_document_is_returned_with_its_exact_text():
    use_case = _FakeUseCase(output=_document_output())
    client = _client(get_application_document_use_case, use_case)

    response = client.get("/api/application-documents/doc-1")

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == _RESUME_TEXT
    assert body["version"] == 2
    assert body["content_sha256"] == "a" * 64
    assert body["backing_sources"] == ["parsed_resume"]


def test_the_document_read_is_scoped_to_the_authenticated_user():
    """The user id comes from the token, never from the request."""
    use_case = _FakeUseCase(output=_document_output())
    client = _client(get_application_document_use_case, use_case)

    client.get("/api/application-documents/doc-1")

    assert use_case.received.user_id == "user-123"
    assert use_case.received.document_id == "doc-1"


def test_an_unknown_or_someone_elses_document_is_a_404():
    use_case = _FakeUseCase(error=ApplicationDocumentNotFoundError("doc-9"))
    client = _client(get_application_document_use_case, use_case)

    response = client.get("/api/application-documents/doc-9")

    assert response.status_code == 404


def test_a_document_that_no_longer_matches_its_digest_is_not_served():
    """Corrupted record, not a bad request — refusing beats presenting
    altered content as what the candidate sent."""
    use_case = _FakeUseCase(
        error=DocumentSnapshotIntegrityError(
            document_id="doc-1", expected_digest="a" * 64, actual_digest="c" * 64
        )
    )
    client = _client(get_application_document_use_case, use_case)

    response = client.get("/api/application-documents/doc-1")

    assert response.status_code == 500


# ---- reading the latest for a job -------------------------------------------


def test_the_latest_document_for_a_job_comes_back_with_its_kind_and_version():
    use_case = _FakeUseCase(output=_document_output())
    client = _client(get_latest_application_document_use_case, use_case)

    response = client.get("/api/job-postings/job-1/documents/tailored_resume/latest")

    assert response.status_code == 200
    assert response.json()["document_kind"] == "tailored_resume"
    assert use_case.received.job_posting_id == "job-1"
    assert use_case.received.document_kind == "tailored_resume"


def test_a_job_with_nothing_stored_is_a_404():
    use_case = _FakeUseCase(
        error=NoStoredApplicationDocumentError(
            job_posting_id="job-1", document_kind="cover_letter"
        )
    )
    client = _client(get_latest_application_document_use_case, use_case)

    response = client.get("/api/job-postings/job-1/documents/cover_letter/latest")

    assert response.status_code == 404


def test_an_unrecognized_document_kind_is_a_422():
    use_case = _FakeUseCase(error=InvalidValueError("'portfolio' is not a kind."))
    client = _client(get_latest_application_document_use_case, use_case)

    response = client.get("/api/job-postings/job-1/documents/portfolio/latest")

    assert response.status_code == 422


# ---- listing ----------------------------------------------------------------


def test_the_tracker_feed_lists_summaries_without_document_text():
    use_case = _FakeUseCase(output=[_summary_output(), _summary_output(id="doc-2")])
    client = _client(get_list_application_documents_use_case, use_case)

    response = client.get("/api/application-documents")

    assert response.status_code == 200
    body = response.json()
    assert [entry["id"] for entry in body] == ["doc-1", "doc-2"]
    assert "content" not in body[0]
    assert body[0]["content_sha256"] == "b" * 64


def test_listing_every_document_is_not_scoped_to_a_job():
    use_case = _FakeUseCase(output=[])
    client = _client(get_list_application_documents_use_case, use_case)

    client.get("/api/application-documents?limit=10")

    assert use_case.received.job_posting_id is None
    assert use_case.received.limit == 10
    assert use_case.received.user_id == "user-123"


def test_one_jobs_documents_can_be_listed_on_their_own():
    use_case = _FakeUseCase(output=[_summary_output()])
    client = _client(get_list_application_documents_use_case, use_case)

    response = client.get("/api/job-postings/job-1/documents")

    assert response.status_code == 200
    assert use_case.received.job_posting_id == "job-1"


def test_an_out_of_range_limit_is_rejected_before_the_use_case_runs():
    use_case = _FakeUseCase(output=[])
    client = _client(get_list_application_documents_use_case, use_case)

    response = client.get("/api/application-documents?limit=0")

    assert response.status_code == 422
    assert use_case.received is None


# ---- the store is read-only over HTTP ---------------------------------------


def test_there_is_no_route_that_writes_or_edits_a_stored_document():
    """A POST/PUT/DELETE here would either accept text the provenance guard
    never saw or let a record of what was sent be changed."""
    schema = create_app().openapi()

    for path in (
        "/api/application-documents",
        "/api/application-documents/{document_id}",
        "/api/job-postings/{job_posting_id}/documents",
        "/api/job-postings/{job_posting_id}/documents/{document_kind}/latest",
    ):
        assert set(schema["paths"][path]) == {"get"}, path
