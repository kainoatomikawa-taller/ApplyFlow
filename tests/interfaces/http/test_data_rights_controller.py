"""Tests for the privacy router: auth gating, export, erasure confirmation, and
the consent endpoints.

Uses FastAPI's dependency_overrides with in-memory fakes, so no real database is
required.

Two of these are about the endpoints refusing rather than working, and they are
the ones worth having: an erasure that runs without confirmation, and an
incomplete export served as a 200.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.data_rights_dtos import (
    ConsentStateOutput,
    DeferredCategoryOutput,
    ErasedCategoryOutput,
    ErasureOutput,
    ExportedCategoryOutput,
    PersonalDataExportOutput,
    RecordConsentOutput,
)
from src.application.exceptions import (
    ErasureNotAcknowledgedError,
    PersonalDataCoverageError,
    UnknownConsentPurposeError,
)
from src.domain.exceptions import ConsentNotWithdrawableError
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_current_user,
    get_erase_user_data_use_case,
    get_export_user_data_use_case,
    get_list_user_consents_use_case,
    get_privacy_policy_version,
    get_record_consent_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
_POLICY = "2026-08-03"

_EXPORT = PersonalDataExportOutput(
    format_version="1.0",
    subject_user_id="user-123",
    generated_at=_NOW,
    consent_policy_version=_POLICY,
    categories=(
        ExportedCategoryOutput(
            key="resumes",
            description="Résumés you uploaded.",
            store="primary_database",
            lawful_basis="contract",
            record_count=1,
            records=({"id": "resume-1", "original_filename": "cv.pdf"},),
        ),
    ),
    deferred_categories=(
        DeferredCategoryOutput(
            key="employer_disclosures",
            description="What employers received.",
            store="third_party_controller",
            lawful_basis="consent",
            disposition="delegated",
            note="Ask the employer directly.",
        ),
    ),
    consents=(
        ConsentStateOutput(
            purpose="answer_reuse",
            description="Keeping your answers.",
            lawful_basis="consent",
            granted=True,
            decided=True,
            withdrawable=True,
            decided_at=_NOW,
            policy_version=_POLICY,
        ),
    ),
    consent_history=(),
    limitations=("Something could not be searched.",),
)

_RECEIPT = ErasureOutput(
    subject_user_id="user-123",
    executed_at=_NOW,
    erased=(
        ErasedCategoryOutput(
            key="resumes",
            description="Résumés you uploaded.",
            store="primary_database",
            records_erased=2,
        ),
    ),
    retained=(
        DeferredCategoryOutput(
            key="consents",
            description="Your privacy choices.",
            store="primary_database",
            lawful_basis="legal_obligation",
            disposition="retain_legal_basis",
            note="Kept as the record that this erasure was lawful.",
        ),
    ),
    consents_withdrawn=("answer_reuse",),
)


class _FakeUseCase:
    """Returns `output`, or raises `error`. Records what it was called with, so
    the tests can assert the controller passed the token's identity rather than
    anything from the request."""

    def __init__(self, output: object = None, error: Exception | None = None) -> None:
        self._output = output
        self._error = error
        self.calls: list[object] = []

    async def execute(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        return self._output


def _provider(value: object) -> Callable[[], object]:
    """A zero-argument override provider.

    Deliberately not `lambda v=value: v`: FastAPI introspects an override's
    signature, so a parameter with a default becomes a *query parameter* and the
    override stops being the object under test. That failure is quiet — the
    endpoint still answers 200 with something that looks right — so the shape of
    this helper is load-bearing.
    """

    def provide() -> object:
        return value

    return provide


def _app(**overrides: object) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_current_user] = _provider(_USER)
    app.dependency_overrides[get_privacy_policy_version] = _provider(_POLICY)
    for dependency, value in overrides.items():
        app.dependency_overrides[_DEPENDENCIES[dependency]] = _provider(value)
    return app


_DEPENDENCIES = {
    "export": get_export_user_data_use_case,
    "erase": get_erase_user_data_use_case,
    "consents": get_list_user_consents_use_case,
    "record": get_record_consent_use_case,
}


# -- Auth gating -------------------------------------------------------------


def test_every_privacy_endpoint_requires_a_bearer_token() -> None:
    """The router carries the auth dependency, which is also what opens the
    decryption scope an export needs — so "authenticated" and "may read this" are
    the same thing here."""
    client = TestClient(create_app())
    assert client.get("/api/privacy/export").status_code == 401
    assert client.post("/api/privacy/erasure", json={}).status_code == 401
    assert client.get("/api/privacy/consents").status_code == 401
    assert (
        client.put(
            "/api/privacy/consents/answer_reuse", json={"granted": True}
        ).status_code
        == 401
    )


# -- Export ------------------------------------------------------------------


def test_export_returns_the_portable_copy_with_its_deferred_sections() -> None:
    use_case = _FakeUseCase(_EXPORT)
    client = TestClient(_app(export=use_case))

    response = client.get("/api/privacy/export")

    assert response.status_code == 200
    body = response.json()
    assert body["subject_user_id"] == "user-123"
    assert body["categories"][0]["records"][0]["original_filename"] == "cv.pdf"
    assert body["deferred_categories"][0]["key"] == "employer_disclosures"
    assert body["consents"][0]["purpose"] == "answer_reuse"
    assert body["limitations"] == ["Something could not be searched."]


def test_export_identifies_the_subject_from_the_token_only() -> None:
    """No endpoint here takes a user id or an email. The export is of whoever the
    verified token names, which is what keeps this from being an admin surface
    with no authorization story."""
    use_case = _FakeUseCase(_EXPORT)
    TestClient(_app(export=use_case)).get("/api/privacy/export")

    args, _kwargs = use_case.calls[0]
    subject = args[0]
    assert subject.user_id == "user-123"
    assert subject.email == "dev@example.com"


def test_an_incomplete_export_is_a_500_rather_than_a_partial_200() -> None:
    """Returning the sections that did resolve would deliver a copy whose gaps
    are indistinguishable from having no data there."""
    use_case = _FakeUseCase(
        error=PersonalDataCoverageError("data export", ("answer_memories",))
    )
    response = TestClient(_app(export=use_case), raise_server_exceptions=False).get(
        "/api/privacy/export"
    )

    assert response.status_code == 500


def test_no_privacy_endpoint_takes_a_personal_identifier_in_its_url() -> None:
    """ADR 0003, checked here as well as by the global URL guard: a query string
    or path segment is recorded in access logs and browser history, and these are
    the endpoints most tempting to key by email."""
    spec = create_app().openapi()
    privacy_paths = [path for path in spec["paths"] if path.startswith("/api/privacy")]
    assert privacy_paths, "the privacy router must be registered"
    for path, operations in spec["paths"].items():
        if not path.startswith("/api/privacy"):
            continue
        for operation in operations.values():
            names = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") in {"query", "path"}
            }
            assert names <= {"purpose"}, (path, names)


# -- Erasure -----------------------------------------------------------------


def test_erasure_returns_a_receipt_of_what_was_deleted_and_what_was_kept() -> None:
    use_case = _FakeUseCase(_RECEIPT)
    client = TestClient(_app(erase=use_case))

    response = client.post("/api/privacy/erasure", json={"acknowledged": True})

    assert response.status_code == 200
    body = response.json()
    assert body["total_records_erased"] == 2
    assert body["erased"][0]["key"] == "resumes"
    assert body["retained"][0]["key"] == "consents"
    assert body["consents_withdrawn"] == ["answer_reuse"]


def test_an_unacknowledged_erasure_is_a_400() -> None:
    """A 400 rather than a no-op 200, so a client that forgot is told instead of
    believing the erasure ran."""
    use_case = _FakeUseCase(error=ErasureNotAcknowledgedError())
    response = TestClient(_app(erase=use_case)).post(
        "/api/privacy/erasure", json={"acknowledged": False}
    )

    assert response.status_code == 400


def test_erasure_defaults_to_unacknowledged_on_an_empty_body() -> None:
    """The schema's default is False, so an accidental POST with no body reaches
    the use case as unacknowledged rather than as a confirmed request."""
    use_case = _FakeUseCase(_RECEIPT)
    TestClient(_app(erase=use_case)).post("/api/privacy/erasure", json={})

    args, _kwargs = use_case.calls[0]
    assert args[0].acknowledged is False


def test_erasure_stamps_the_policy_version_from_the_deployment() -> None:
    """Not from the body: a client that could assert which notice it had shown
    could record consent — here, a withdrawal — against a notice the user never
    saw."""
    use_case = _FakeUseCase(_RECEIPT)
    TestClient(_app(erase=use_case)).post(
        "/api/privacy/erasure", json={"acknowledged": True, "policy_version": "fake"}
    )

    args, _kwargs = use_case.calls[0]
    assert args[0].policy_version == _POLICY


# -- Consent -----------------------------------------------------------------


def test_listing_consents_returns_every_purpose() -> None:
    states = [
        ConsentStateOutput(
            purpose="answer_reuse",
            description="Keeping your answers.",
            lawful_basis="consent",
            granted=False,
            decided=False,
            withdrawable=True,
            decided_at=None,
            policy_version=None,
        )
    ]
    response = TestClient(_app(consents=_FakeUseCase(states))).get(
        "/api/privacy/consents"
    )

    assert response.status_code == 200
    assert response.json()[0]["decided"] is False


def test_recording_a_consent_decision_reports_whether_anything_changed() -> None:
    output = RecordConsentOutput(state=_EXPORT.consents[0], changed=True)
    response = TestClient(_app(record=_FakeUseCase(output))).put(
        "/api/privacy/consents/answer_reuse", json={"granted": True}
    )

    assert response.status_code == 200
    assert response.json()["changed"] is True
    assert response.json()["state"]["granted"] is True


def test_an_unknown_purpose_is_a_404() -> None:
    use_case = _FakeUseCase(
        error=UnknownConsentPurposeError("sell_my_data", ("answer_reuse",))
    )
    response = TestClient(_app(record=use_case)).put(
        "/api/privacy/consents/sell_my_data", json={"granted": True}
    )

    assert response.status_code == 404


def test_withdrawing_a_non_withdrawable_purpose_is_a_409_pointing_at_erasure() -> None:
    """The request is well-formed and the purpose is real; what cannot be done is
    stop this processing while the account exists."""
    use_case = _FakeUseCase(
        error=ConsentNotWithdrawableError("account_and_applications")
    )
    response = TestClient(_app(record=use_case)).put(
        "/api/privacy/consents/account_and_applications", json={"granted": False}
    )

    assert response.status_code == 409
    assert "eras" in response.json()["detail"].lower()


def test_the_consent_purpose_travels_in_the_path_and_the_answer_in_the_body() -> None:
    use_case = _FakeUseCase(
        RecordConsentOutput(state=_EXPORT.consents[0], changed=False)
    )
    TestClient(_app(record=use_case)).put(
        "/api/privacy/consents/answer_reuse", json={"granted": False}
    )

    args, _kwargs = use_case.calls[0]
    assert args[0].purpose == "answer_reuse"
    assert args[0].granted is False
    assert args[0].user_id == "user-123"
