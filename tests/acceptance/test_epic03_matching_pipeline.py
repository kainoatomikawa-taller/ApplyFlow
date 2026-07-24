"""Epic 03 acceptance check — the matching pipeline's Definition of Done.

Runs the ONE flow described in `docs/epic-03-acceptance-check.md` against
REAL infrastructure (a real Postgres database, a real Anthropic API key,
and the real HTTP app with real Supabase-JWT auth) — no fakes, no mocks,
no dependency overrides. Opt-in, like `test_epic00_skeleton.py` and the
other real-infra tests in this suite, so `pytest` never touches a real
database or spends money unless a developer deliberately asks for it:

    RUN_EPIC03_ACCEPTANCE_TEST=1 pytest tests/acceptance -v -s

Requires, via `.env` or exported env vars:
    DATABASE_URL          a reachable Postgres (local `docker compose up db`
                           or a Supabase project)
    SUPABASE_JWT_SECRET    used both to mint this test's bearer token and by
                           the app to verify it, so the run proves the real
                           auth path rather than bypassing it
    ANTHROPIC_API_KEY      a pay-as-you-go key — the ranked-list call makes
                           one real (cheap-tier) rationale-generation call

The single flow, in order:
  1. Seed one candidate profile — a "sophomore": high-school diploma
     only, a U.S. citizen, one `Python` skill — directly through
     `SqlAlchemyProfileRepository` (there's no HTTP profile-creation
     route yet), and two job postings directly through
     `SqlAlchemyJobPostingRepository`:
       - a Senior Research Scientist role that genuinely REQUIRES a
         doctorate (`degree_required=True`) — a real hard disqualifier
         for this candidate.
       - a Junior Software Engineer role that only PREFERS a doctorate
         (`degree_required=False`) and wants Python — reachable; the PhD
         mention is a wish-list item, not a gate.
     This is the "PhD role vs sophomore" over/under-filtering case: the
     engine must filter the first (an unreachable role) without also
     filtering the second (a reachable one the PhD mention shouldn't
     exclude).
  2. Authenticate with a real Supabase-shaped JWT and GET
     `/api/job-postings/matches` through the real HTTP app: assert the
     doctorate-required posting is absent, the Python posting is present
     with a numeric score, a non-empty LLM-written rationale, and
     "Doctorate preferred" in its gap list — proving criteria 1 and 2 in
     one call. An unauthenticated call to the same route is also checked
     to fail, proving the auth gate is live, not bypassed.
  3. POST a thumbs-up reaction to the reachable posting via
     `/api/job-postings/{id}/feedback`, tagged with the score from step 2,
     then GET `/api/job-postings/feedback` and confirm it comes back —
     proving criterion 3: feedback recorded and retrievable through the
     data-access layer.
"""

from __future__ import annotations

import os
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)
from src.infrastructure.config import get_settings
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    dispose_engine,
    engine,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.persistence.profile_repository_impl import (
    SqlAlchemyProfileRepository,
)
from src.interfaces.http.app import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_EPIC03_ACCEPTANCE_TEST") != "1",
    reason=(
        "opt-in: set RUN_EPIC03_ACCEPTANCE_TEST=1 with DATABASE_URL, "
        "SUPABASE_JWT_SECRET, and ANTHROPIC_API_KEY configured to run the "
        "Epic 03 Definition-of-Done check (see "
        "docs/epic-03-acceptance-check.md)"
    ),
)


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


def _mint_bearer_token(secret: str, user_id: str) -> str:
    payload = {
        "sub": user_id,
        "aud": "authenticated",
        "email": f"{user_id}@example.com",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.mark.asyncio
async def test_epic03_definition_of_done(schema_ready: None) -> None:
    get_settings.cache_clear()
    settings = get_settings()

    jwt_secret = settings.supabase_jwt_secret.get_secret_value()
    if not jwt_secret:
        pytest.skip("SUPABASE_JWT_SECRET is not configured; cannot mint a test token")
    if not settings.anthropic_api_key.get_secret_value():
        pytest.skip("ANTHROPIC_API_KEY is not configured")

    # `schema_ready` may run on a different event loop than this test body
    # under pytest-asyncio's fixture/test loop scoping — see the
    # loop-handoff note further down for why this matters.
    await dispose_engine()

    run_id = uuid.uuid4()
    user_id = f"epic03-sophomore-{run_id}"
    token = _mint_bearer_token(jwt_secret, user_id)
    http_client = TestClient(create_app())

    doctorate_job_id = f"epic03-phd-role-{run_id}"
    reachable_job_id = f"epic03-junior-role-{run_id}"

    # ---- seed: one candidate ("sophomore") + two postings ---------------------
    profile = UserProfile(
        id=f"epic03-profile-{run_id}",
        user_id=user_id,
        full_name="Epic 03 Sophomore Candidate",
        email=EmailAddress(f"{user_id}@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
        highest_degree=DegreeLevel.HIGH_SCHOOL,
        work_authorization=WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            source=ProvenanceSource.USER_ENTERED,
        ),
    )
    profile.add_skill(
        Skill(
            id=f"epic03-skill-{run_id}",
            name="Python",
            source=ProvenanceSource.USER_ENTERED,
        )
    )

    doctorate_required_posting = JobPosting(
        id=doctorate_job_id,
        source="acceptance-test",
        company="Epic 03 Research Labs",
        title="Senior Research Scientist",
        apply_url=f"https://example.com/jobs/{doctorate_job_id}",
        description=(
            "PhD in Computer Science required. Deep expertise in "
            "distributed systems research."
        ),
    )
    doctorate_required_posting.set_requirements(
        JobRequirements(degree_level=DegreeLevel.DOCTORATE, degree_required=True)
    )

    reachable_posting = JobPosting(
        id=reachable_job_id,
        source="acceptance-test",
        company="Epic 03 Startup Co",
        title="Junior Software Engineer",
        apply_url=f"https://example.com/jobs/{reachable_job_id}",
        description=(
            "Entry-level engineering role. PhD a plus but not required. "
            "Python experience wanted."
        ),
    )
    reachable_posting.set_requirements(
        JobRequirements(
            degree_level=DegreeLevel.DOCTORATE,
            degree_required=False,
            required_skills=("Python",),
        )
    )

    async with async_session_factory() as session:
        await SqlAlchemyProfileRepository(session).add(profile)
        job_posting_repository = SqlAlchemyJobPostingRepository(session)
        await job_posting_repository.add(doctorate_required_posting)
        await job_posting_repository.add(reachable_posting)

    # `TestClient` drives each request's DB access through its own
    # short-lived event loop (a fresh one per call, not shared with this
    # test coroutine's, and not necessarily reused between calls either)
    # — reusing a pooled connection opened on one loop from another raises
    # asyncpg's "attached to a different loop" error. Disposing the shared
    # engine's pool before every DB-touching call forces a fresh
    # connection on the loop that call actually runs on.
    await dispose_engine()

    try:
        # ---- 1/2. authenticate + fetch the ranked, filtered, scored list ---
        matches_response = http_client.get(
            "/api/job-postings/matches",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert matches_response.status_code == 200, matches_response.text
        matches = matches_response.json()

        matched_ids = {entry["job_posting"]["id"] for entry in matches}
        assert doctorate_job_id not in matched_ids, (
            "a genuine hard disqualifier (PhD required) must be filtered out"
        )
        assert reachable_job_id in matched_ids, (
            "a reachable role (PhD merely preferred) must not be over-filtered"
        )

        reachable_entry = next(
            entry
            for entry in matches
            if entry["job_posting"]["id"] == reachable_job_id
        )
        assert isinstance(reachable_entry["score"], int)
        assert 0 <= reachable_entry["score"] <= 100
        assert reachable_entry["rationale"].strip() != ""
        assert any(
            "doctorate" in gap.lower() for gap in reachable_entry["gaps"]
        ), reachable_entry["gaps"]

        # The same route must still reject an unauthenticated caller —
        # proving this flow exercises the real auth gate, not a bypass.
        unauthenticated = http_client.get("/api/job-postings/matches")
        assert unauthenticated.status_code == 401

        # ---- 3. record + retrieve thumbs-up feedback ------------------------
        await dispose_engine()  # see the loop-handoff note above
        feedback_response = http_client.post(
            f"/api/job-postings/{reachable_job_id}/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "rating": "thumbs_up",
                "score_at_feedback": reachable_entry["score"],
            },
        )
        assert feedback_response.status_code == 201, feedback_response.text
        feedback_id = feedback_response.json()["id"]

        await dispose_engine()  # see the loop-handoff note above
        feedback_history_response = http_client.get(
            "/api/job-postings/feedback",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert feedback_history_response.status_code == 200
        feedback_history = feedback_history_response.json()

        recorded = next(
            entry for entry in feedback_history if entry["id"] == feedback_id
        )
        assert recorded["job_posting_id"] == reachable_job_id
        assert recorded["rating"] == "thumbs_up"
        assert recorded["score_at_feedback"] == reachable_entry["score"]
    finally:
        # The candidate profile is cleaned up. The two seeded job postings
        # and the recorded feedback row are left in place deliberately —
        # they're the artifact this check exists to prove exists, and
        # `JobPostingRepository`/`JobMatchFeedbackRepository` don't expose
        # a delete method (postings and feedback are long-lived/append-only
        # by design) — see `docs/epic-03-acceptance-check.md`.
        await dispose_engine()  # see the loop-handoff note above
        async with async_session_factory() as session:
            await SqlAlchemyProfileRepository(session).delete(profile.id)
