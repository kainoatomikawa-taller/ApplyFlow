"""Tests for the profile router: auth gating, the create-or-update contact
section, the per-section saves, and the two sensitive sections.

Uses FastAPI's dependency_overrides with in-memory fakes, so no real database is
required.

The tests worth reading first are the ones about *refusing*: a section touched
before a profile exists, a legal declaration stored without the candidate agreeing
to it, and a personal identifier reaching a URL. Those are the ones a regression
would make quietly wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.profile_dtos import (
    AddressOutput,
    EeoSelfIdentificationOutput,
    ProfileLinksOutput,
    ProfileOutput,
    QualificationsOutput,
    WorkAuthorizationOutput,
)
from src.application.exceptions import (
    SensitiveStorageNotAcknowledgedError,
    UnknownProfileEnumValueError,
)
from src.domain.exceptions import (
    BusinessRuleViolationError,
    ProfileEntryNotFoundError,
    ProfileNotFoundError,
)
from src.interfaces.http.app import create_app
from src.interfaces.http.dependencies import (
    get_current_user,
    get_eeo_self_identification_use_case,
    get_privacy_policy_version,
    get_profile_use_case,
    get_remove_skill_use_case,
    get_save_contact_details_use_case,
    get_save_eeo_self_identification_use_case,
    get_save_skill_use_case,
    get_save_work_authorization_use_case,
    get_save_work_history_entry_use_case,
    get_update_profile_address_use_case,
    get_work_authorization_use_case,
)

_USER = AuthenticatedUserDTO(subject="user-123", email="dev@example.com")
_NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
_POLICY = "2026-08-03"

_PROFILE = ProfileOutput(
    id="profile-1",
    user_id="user-123",
    full_name="Dana Reyes",
    email="dana@example.com",
    contact_source="user_entered",
    phone="+1 512 555 0100",
    headline="Backend engineer",
    location="Austin, TX",
    created_at=_NOW,
    updated_at=_NOW,
    middle_name="Quinn",
    preferred_name="Dee",
    address=AddressOutput(
        street_address="1 Test Way",
        city="Austin",
        state_or_region="TX",
        postal_code="78701",
        country="USA",
        source="user_entered",
    ),
    links=ProfileLinksOutput(
        portfolio_url=None,
        linkedin_url="https://www.linkedin.com/in/danareyes",
        github_url=None,
        source="user_entered",
    ),
    qualifications=QualificationsOutput(clearance_level=None, highest_degree="masters"),
)

_WORK_AUTH = WorkAuthorizationOutput(
    status="citizen",
    citizenship_country="USA",
    visa_type=None,
    requires_sponsorship=False,
    details=None,
    source="user_entered",
    is_candidate_attested=True,
    consent_granted=True,
)

_EEO = EeoSelfIdentificationOutput(
    gender_identity="decline_to_self_identify",
    race_ethnicity=None,
    veteran_status=None,
    disability_status=None,
    source="user_entered",
    consent_granted=True,
)


class _FakeUseCase:
    """Returns `output`, or raises `error`. Records its calls so a test can assert
    the controller passed the token's identity rather than anything from the
    request."""

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

    Not `lambda v=value: v`: FastAPI introspects an override's signature, so a
    parameter with a default becomes a query parameter and the override silently
    stops being the object under test.
    """

    def provide() -> object:
        return value

    return provide


_DEPENDENCIES = {
    "get": get_profile_use_case,
    "contact": get_save_contact_details_use_case,
    "address": get_update_profile_address_use_case,
    "save_skill": get_save_skill_use_case,
    "remove_skill": get_remove_skill_use_case,
    "save_job": get_save_work_history_entry_use_case,
    "get_auth": get_work_authorization_use_case,
    "save_auth": get_save_work_authorization_use_case,
    "get_eeo": get_eeo_self_identification_use_case,
    "save_eeo": get_save_eeo_self_identification_use_case,
}


def _app(**overrides: object) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_current_user] = _provider(_USER)
    app.dependency_overrides[get_privacy_policy_version] = _provider(_POLICY)
    for name, value in overrides.items():
        app.dependency_overrides[_DEPENDENCIES[name]] = _provider(value)
    return app


# -- Auth and URL hygiene ------------------------------------------------------


def test_every_profile_endpoint_requires_a_bearer_token() -> None:
    """The router carries the auth dependency, which is also what opens the
    decryption scope the profile read needs — so "authenticated" and "may read
    this" are the same thing here."""
    client = TestClient(create_app())
    assert client.get("/api/profile").status_code == 401
    assert client.put("/api/profile/contact", json={}).status_code == 401
    assert client.get("/api/profile/work-authorization").status_code == 401
    assert client.get("/api/profile/eeo").status_code == 401


def test_no_profile_endpoint_takes_a_personal_identifier_in_its_url() -> None:
    """ADR 0003. The subject comes from the token, so the only path parameters
    here are opaque entry ids — a URL is recorded in access logs and browser
    history, which is not somewhere a name or an email may go."""
    spec = create_app().openapi()
    profile_paths = [p for p in spec["paths"] if p.startswith("/api/profile")]
    assert profile_paths, "the profile router must be registered"
    allowed = {"entry_id", "skill_id"}
    for path, operations in spec["paths"].items():
        if not path.startswith("/api/profile"):
            continue
        for operation in operations.values():
            names = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") in {"query", "path"}
            }
            assert names <= allowed, (path, names)


# -- Reading -------------------------------------------------------------------


def test_getting_the_profile_returns_every_section() -> None:
    response = TestClient(_app(get=_FakeUseCase(_PROFILE))).get("/api/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Dana Reyes"
    assert body["middle_name"] == "Quinn"
    assert body["preferred_name"] == "Dee"
    assert body["address"]["city"] == "Austin"
    assert body["links"]["linkedin_url"].endswith("danareyes")
    assert body["qualifications"]["highest_degree"] == "masters"


def test_the_profile_payload_never_carries_the_eeo_record() -> None:
    """It has its own endpoint. Keeping it out of the payload every profile view
    loads is what lets the main mapper stay off the list of modules allowed to read
    it at all."""
    response = TestClient(_app(get=_FakeUseCase(_PROFILE))).get("/api/profile")
    body = response.json()
    for key in ("gender_identity", "race_ethnicity", "veteran_status", "eeo"):
        assert key not in body


def test_a_missing_profile_is_a_404_that_names_the_remedy() -> None:
    """ "Not found" alone is not actionable: the candidate has to be told that one
    specific section creates the profile."""
    use_case = _FakeUseCase(error=ProfileNotFoundError("user-123"))
    response = TestClient(_app(get=use_case)).get("/api/profile")

    assert response.status_code == 404
    assert "contact" in response.json()["detail"]


# -- Contact: the section that creates a profile -------------------------------


def test_saving_contact_details_works_with_no_profile_yet() -> None:
    """The endpoint that makes a résumé optional. It is the only one here that does
    not require an existing profile, because name and email are the only mandatory
    fields on the record."""
    use_case = _FakeUseCase(_PROFILE)
    response = TestClient(_app(contact=use_case)).put(
        "/api/profile/contact",
        json={"full_name": "Dana Reyes", "email": "dana@example.com"},
    )

    assert response.status_code == 200
    args, _kwargs = use_case.calls[0]
    assert args[0].user_id == "user-123", "the subject comes from the token"


def test_contact_details_require_a_name_and_an_email() -> None:
    response = TestClient(_app(contact=_FakeUseCase(_PROFILE))).put(
        "/api/profile/contact", json={"full_name": "  "}
    )
    assert response.status_code == 422


def test_the_two_other_names_are_passed_through_including_blank() -> None:
    """Blank is an answer, not an omission: no middle name, and no preferred name
    distinct from the legal one."""
    use_case = _FakeUseCase(_PROFILE)
    TestClient(_app(contact=use_case)).put(
        "/api/profile/contact",
        json={
            "full_name": "Dana Reyes",
            "email": "dana@example.com",
            "middle_name": "",
            "preferred_name": "Dee",
        },
    )

    args, _kwargs = use_case.calls[0]
    assert args[0].middle_name == ""
    assert args[0].preferred_name == "Dee"


# -- The other sections require a profile --------------------------------------


def test_a_section_touched_before_the_profile_exists_is_a_404() -> None:
    use_case = _FakeUseCase(error=ProfileNotFoundError("user-123"))
    response = TestClient(_app(address=use_case)).put(
        "/api/profile/address", json={"city": "Austin"}
    )

    assert response.status_code == 404
    assert "contact" in response.json()["detail"]


def test_a_stale_entry_id_is_a_404_rather_than_an_insert() -> None:
    """An edit against an id the profile does not hold means the client is working
    from a list that has changed. Appending a duplicate is the one outcome nobody
    expects from a control labelled "edit"."""
    use_case = _FakeUseCase(error=ProfileEntryNotFoundError("Work history", "job-404"))
    response = TestClient(_app(save_job=use_case)).put(
        "/api/profile/work-history/job-404",
        json={
            "company_name": "Initech",
            "job_title": "Engineer",
            "start_date": "2020-01-01",
        },
    )

    assert response.status_code == 404


def test_a_duplicate_skill_name_is_a_conflict_not_a_validation_error() -> None:
    """The request is well-formed and the name is fine — it is the profile's current
    contents that make it a conflict, which is a 409."""
    use_case = _FakeUseCase(
        error=BusinessRuleViolationError("Skill 'Python' already exists.")
    )
    response = TestClient(_app(save_skill=use_case)).post(
        "/api/profile/skills", json={"name": "python"}
    )

    assert response.status_code == 409


def test_an_unrecognized_enum_value_is_a_422() -> None:
    use_case = _FakeUseCase(
        error=UnknownProfileEnumValueError("proficiency", "wizard", ("expert",))
    )
    response = TestClient(_app(save_skill=use_case)).post(
        "/api/profile/skills", json={"name": "Python", "proficiency": "wizard"}
    )

    assert response.status_code == 422
    assert "expert" in response.json()["detail"]


def test_adding_an_entry_returns_201_and_the_whole_profile() -> None:
    """The whole profile rather than the entry, so a client re-renders from what was
    stored instead of merging a partial response into local state."""
    response = TestClient(_app(save_job=_FakeUseCase(_PROFILE))).post(
        "/api/profile/work-history",
        json={
            "company_name": "Initech",
            "job_title": "Engineer",
            "start_date": "2020-01-01",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == "profile-1"


def test_deleting_an_entry_returns_the_updated_profile() -> None:
    response = TestClient(_app(remove_skill=_FakeUseCase(_PROFILE))).delete(
        "/api/profile/skills/skill-1"
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Dana Reyes"


# -- Work authorization --------------------------------------------------------


def test_reading_work_authorization_reports_attestation_and_consent() -> None:
    """Both flags are what let the editor explain itself: attestation is why a
    résumé-derived record still gets handed back on every form, and consent is what
    pre-ticks the acknowledgement."""
    response = TestClient(_app(get_auth=_FakeUseCase(_WORK_AUTH))).get(
        "/api/profile/work-authorization"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_candidate_attested"] is True
    assert body["consent_granted"] is True
    assert body["requires_sponsorship"] is False


def test_saving_work_authorization_stamps_the_deployments_policy_version() -> None:
    """Not the body's. A client that could assert which notice it had shown could
    record consent against a notice the candidate never saw."""
    use_case = _FakeUseCase(_WORK_AUTH)
    TestClient(_app(save_auth=use_case)).put(
        "/api/profile/work-authorization",
        json={
            "status": "citizen",
            "consent_acknowledged": True,
            "policy_version": "attacker-supplied",
        },
    )

    _args, kwargs = use_case.calls[0]
    assert kwargs["policy_version"] == _POLICY


def test_storing_work_authorization_without_acknowledgement_is_a_400() -> None:
    """Special-category data needs a clear affirmative act, and a request merely
    arriving is not one."""
    use_case = _FakeUseCase(
        error=SensitiveStorageNotAcknowledgedError("work authorization")
    )
    response = TestClient(_app(save_auth=use_case)).put(
        "/api/profile/work-authorization",
        json={"status": "citizen", "consent_acknowledged": False},
    )

    assert response.status_code == 400
    assert "acknowledge" in response.json()["detail"].lower()


def test_the_acknowledgement_defaults_to_false() -> None:
    """So a request that forgot the field is refused rather than treated as
    agreement."""
    use_case = _FakeUseCase(_WORK_AUTH)
    TestClient(_app(save_auth=use_case)).put(
        "/api/profile/work-authorization", json={"status": "citizen"}
    )

    args, _kwargs = use_case.calls[0]
    assert args[0].consent_acknowledged is False


def test_clearing_work_authorization_needs_no_acknowledgement() -> None:
    """Consent is required to store this data, not to delete it."""
    use_case = _FakeUseCase(
        WorkAuthorizationOutput(
            status=None,
            citizenship_country=None,
            visa_type=None,
            requires_sponsorship=None,
            details=None,
            source=None,
            is_candidate_attested=False,
            consent_granted=True,
        )
    )
    response = TestClient(_app(save_auth=use_case)).put(
        "/api/profile/work-authorization", json={"status": None}
    )

    assert response.status_code == 200
    assert response.json()["status"] is None


# -- EEO -----------------------------------------------------------------------


def test_the_eeo_record_has_its_own_endpoint() -> None:
    response = TestClient(_app(get_eeo=_FakeUseCase(_EEO))).get("/api/profile/eeo")

    assert response.status_code == 200
    assert response.json()["gender_identity"] == "decline_to_self_identify"


def test_storing_eeo_without_acknowledgement_is_a_400() -> None:
    use_case = _FakeUseCase(
        error=SensitiveStorageNotAcknowledgedError("EEO self-identification")
    )
    response = TestClient(_app(save_eeo=use_case)).put(
        "/api/profile/eeo",
        json={"gender_identity": "female", "consent_acknowledged": False},
    )

    assert response.status_code == 400


def test_an_unanswered_eeo_category_stays_unanswered() -> None:
    """None means "I did not answer this", which is a different state from
    `decline_to_self_identify` — itself one of the answers."""
    use_case = _FakeUseCase(_EEO)
    TestClient(_app(save_eeo=use_case)).put(
        "/api/profile/eeo",
        json={"gender_identity": "female", "consent_acknowledged": True},
    )

    args, _kwargs = use_case.calls[0]
    assert args[0].gender_identity == "female"
    assert args[0].race_ethnicity is None
