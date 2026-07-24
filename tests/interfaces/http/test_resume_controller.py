"""Tests for the resumes router: auth gating, upload happy path, and each
clear-error path (unsupported format, oversized file, unreadable file,
unknown id).

Uses FastAPI's dependency_overrides with in-memory fakes, so no real
database, disk, or parsing library is required.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.profile_dtos import ProfileOutput
from src.application.dtos.resume_dtos import ResumeOutput
from src.application.exceptions import ExternalServiceError, TextExtractionError
from src.domain.exceptions import (
    FileTooLargeError,
    ProfileMissingContactInfoError,
    ResumeNotFoundError,
    UnsupportedFileFormatError,
)
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_current_user,
    get_list_resumes_use_case,
    get_parse_resume_use_case,
    get_resume_use_case,
    get_upload_resume_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")

_OUTPUT = ResumeOutput(
    id="resume-1",
    original_filename="resume.txt",
    content_type="text/plain",
    size_bytes=13,
    extracted_text="Jane Doe, SWE",
    created_at=datetime(2024, 1, 1),
)


class _FakeUploadUseCase:
    def __init__(self, output=None, error=None) -> None:
        self._output = output
        self._error = error

    async def execute(self, dto):
        if self._error is not None:
            raise self._error
        return self._output


class _FakeGetUseCase:
    def __init__(self, output=None, error=None) -> None:
        self._output = output
        self._error = error

    async def execute(self, resume_id, user_id):
        if self._error is not None:
            raise self._error
        return self._output


class _FakeListUseCase:
    def __init__(self, outputs) -> None:
        self._outputs = outputs

    async def execute(self, user_id):
        return self._outputs


class _FakeParseUseCase:
    def __init__(self, output=None, error=None) -> None:
        self._output = output
        self._error = error

    async def execute(self, resume_id, user_id):
        if self._error is not None:
            raise self._error
        return self._output


_PROFILE_OUTPUT = ProfileOutput(
    id="profile-1",
    user_id="user-123",
    full_name="Jane Doe",
    email="jane@example.com",
    contact_source="parsed_resume",
    phone=None,
    headline=None,
    location=None,
    created_at=datetime(2024, 1, 1),
    updated_at=datetime(2024, 1, 1),
)


def _client(app) -> TestClient:
    return TestClient(app)


def test_upload_without_authorization_header_is_rejected():
    client = _client(create_app())
    response = client.post(
        "/api/resumes", files={"file": ("resume.txt", b"hi", "text/plain")}
    )
    assert response.status_code == 401


def test_upload_happy_path_returns_201():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_upload_resume_use_case] = lambda: _FakeUploadUseCase(
        output=_OUTPUT
    )

    response = _client(app).post(
        "/api/resumes", files={"file": ("resume.txt", b"hi", "text/plain")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "resume-1"
    assert body["extracted_text"] == "Jane Doe, SWE"
    app.dependency_overrides.clear()


def test_upload_unsupported_format_returns_415():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_upload_resume_use_case] = lambda: _FakeUploadUseCase(
        error=UnsupportedFileFormatError("image/png")
    )

    response = _client(app).post(
        "/api/resumes", files={"file": ("photo.png", b"hi", "image/png")}
    )

    assert response.status_code == 415
    app.dependency_overrides.clear()


def test_upload_oversized_file_returns_413():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_upload_resume_use_case] = lambda: _FakeUploadUseCase(
        error=FileTooLargeError(999_999_999, 10_000_000)
    )

    response = _client(app).post(
        "/api/resumes", files={"file": ("resume.pdf", b"hi", "application/pdf")}
    )

    assert response.status_code == 413
    app.dependency_overrides.clear()


def test_upload_unreadable_file_returns_422():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_upload_resume_use_case] = lambda: _FakeUploadUseCase(
        error=TextExtractionError("corrupt file")
    )

    response = _client(app).post(
        "/api/resumes", files={"file": ("resume.pdf", b"hi", "application/pdf")}
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_get_resume_returns_404_for_unknown_id():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_resume_use_case] = lambda: _FakeGetUseCase(
        error=ResumeNotFoundError("does-not-exist")
    )

    response = _client(app).get("/api/resumes/does-not-exist")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_get_resume_happy_path():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_resume_use_case] = lambda: _FakeGetUseCase(
        output=_OUTPUT
    )

    response = _client(app).get("/api/resumes/resume-1")

    assert response.status_code == 200
    assert response.json()["id"] == "resume-1"
    app.dependency_overrides.clear()


def test_list_resumes_returns_only_current_users_resumes():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_list_resumes_use_case] = lambda: _FakeListUseCase(
        [_OUTPUT]
    )

    response = _client(app).get("/api/resumes")

    assert response.status_code == 200
    assert len(response.json()) == 1
    app.dependency_overrides.clear()


def test_parse_resume_happy_path_returns_profile():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_parse_resume_use_case] = lambda: _FakeParseUseCase(
        output=_PROFILE_OUTPUT
    )

    response = _client(app).post("/api/resumes/resume-1/parse")

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Jane Doe"
    assert body["contact_source"] == "parsed_resume"
    app.dependency_overrides.clear()


def test_parse_resume_returns_404_for_unknown_resume():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_parse_resume_use_case] = lambda: _FakeParseUseCase(
        error=ResumeNotFoundError("does-not-exist")
    )

    response = _client(app).post("/api/resumes/does-not-exist/parse")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_parse_resume_returns_422_when_contact_info_cannot_be_determined():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_parse_resume_use_case] = lambda: _FakeParseUseCase(
        error=ProfileMissingContactInfoError()
    )

    response = _client(app).post("/api/resumes/resume-1/parse")

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_parse_resume_returns_502_when_the_llm_call_fails():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_parse_resume_use_case] = lambda: _FakeParseUseCase(
        error=ExternalServiceError("boom")
    )

    response = _client(app).post("/api/resumes/resume-1/parse")

    assert response.status_code == 502
    app.dependency_overrides.clear()
