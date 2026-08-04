"""Epic 00 acceptance check — the skeleton's Definition of Done.

Runs the ONE flow described in `docs/epic-00-acceptance-check.md` against
REAL infrastructure (a real Postgres database and a real Anthropic API
key) — no fakes, no mocks, no dependency overrides. Opt-in, like the
other real-infra tests in this suite (`test_persistence_smoke.py`,
`test_anthropic_llm_client_live.py`), so `pytest` never touches a real
database or spends money unless a developer deliberately asks for it:

    RUN_EPIC00_ACCEPTANCE_TEST=1 pytest tests/acceptance -v -s

Requires, via `.env` or exported env vars:
    DATABASE_URL          a reachable Postgres (local `docker compose up db`
                           or a Supabase project)
    SUPABASE_JWT_SECRET    used both to mint this test's bearer token and by
                           the app to verify it, so the run proves the real
                           auth path rather than bypassing it
    ANTHROPIC_API_KEY      a pay-as-you-go key (see AnthropicLlmClient)

The single flow, in order:
  1. Mint a Supabase-shaped JWT and use it to POST a new job application
     (DB write) and GET it back (DB read) through the real HTTP app —
     an unauthenticated request to the same route is also checked to
     fail, proving the auth gate is live, not bypassed.
  2. Make the same routed LLM call twice through `GetLlmCompletion` with
     a shared, deliberately-long system prompt: the first call creates an
     Anthropic prompt cache entry, the second reads it back — proving
     both caching and that `LlmTaskType.EXTRACTION` routes to the cheap
     tier.
  3. Read the two rows `AnthropicLlmClient` persisted via
     `SqlAlchemyUsageLogger` back out of `llm_usage_records` — proving
     token/cost logging is wired to the data-access layer, not just to
     stdout.

NOT RUNNABLE YET — step 3's feature does not exist. There is no
`llm_usage_logger_impl` module, no `LlmUsageRecordModel`, no
`llm_usage_records` table, and `AnthropicLlmClient.__init__` takes only
`settings` (no `usage_logger`/`id_generator`). Steps 1 and 2 are fully
built; only the persisted token/cost log is outstanding.

So this module self-skips on `_USAGE_LOGGING_BUILT` below, and the two
names that don't resolve yet are imported inside the test rather than at
module scope. That is deliberate: pytest imports every test module during
collection, *before* any skip marker is consulted, so a module-level
import of a missing name is a collection error that aborts the whole
suite — not a skip. The check re-enables itself automatically once the
usage-logging module lands; nothing here needs editing then.
"""

from __future__ import annotations

import importlib.util
import os
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.application.dtos.llm_dtos import LlmCompletionInput
from src.application.ports.llm_client_port import LlmModelTier, LlmTaskType
from src.application.use_cases.get_llm_completion import GetLlmCompletion
from src.infrastructure.config import get_settings
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.job_application_repository_impl import (
    SqlAlchemyJobApplicationRepository,
)
from src.infrastructure.services.uuid_id_generator import UuidIdGenerator
from src.interfaces.http.app import create_app

#: Step 3's feature — the persisted token/cost log. Absent for now (see the
#: module docstring); this module's own gate, so the check turns itself back
#: on when the module appears.
_USAGE_LOGGING_BUILT = (
    importlib.util.find_spec("src.infrastructure.persistence.llm_usage_logger_impl")
    is not None
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_EPIC00_ACCEPTANCE_TEST") != "1",
        reason=(
            "opt-in: set RUN_EPIC00_ACCEPTANCE_TEST=1 with DATABASE_URL, "
            "SUPABASE_JWT_SECRET, and ANTHROPIC_API_KEY configured to run the "
            "Epic 00 Definition-of-Done check (see "
            "docs/epic-00-acceptance-check.md)"
        ),
    ),
    pytest.mark.skipif(
        not _USAGE_LOGGING_BUILT,
        reason=(
            "Epic 00 step 3 is not built: no llm_usage_logger_impl module, no "
            "LlmUsageRecordModel, no llm_usage_records table, and "
            "AnthropicLlmClient takes no usage_logger. Steps 1-2 (auth + DB "
            "read/write, routed and cached LLM call) are built; this check "
            "re-enables itself once the usage log lands."
        ),
    ),
]

# Anthropic only creates a cache entry once a system prompt clears a
# per-model minimum token count (2048 for Haiku). Padded well past that so
# the first call is guaranteed to write the cache and the second to hit it.
_CACHEABLE_SYSTEM_PROMPT = (
    "You are a terse assistant helping verify a deployment skeleton. "
    + ("Treat every request the same way regardless of its content. " * 400)
)


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


def _mint_bearer_token(secret: str, email: str) -> str:
    # The email is a parameter because `GET /api/applications` reads the
    # candidate from this claim rather than from a query string (Epic 07 — no
    # PII in URLs). Passing the run's unique address in keeps each run's rows
    # isolated, which is what the random address used to do.
    payload = {
        "sub": f"epic00-acceptance-{uuid.uuid4()}",
        "aud": "authenticated",
        "email": email,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.mark.asyncio
async def test_epic00_definition_of_done(schema_ready: None, caplog) -> None:
    # Imported here, not at module scope: these two names do not exist until
    # step 3's usage-logging feature is built, and a missing module-level
    # import is a collection error that takes the entire suite down rather
    # than the skip this check is supposed to produce.
    from src.infrastructure.persistence.llm_usage_logger_impl import (
        SqlAlchemyUsageLogger,
    )
    from src.infrastructure.persistence.models import LlmUsageRecordModel

    get_settings.cache_clear()
    settings = get_settings()

    jwt_secret = settings.supabase_jwt_secret.get_secret_value()
    if not jwt_secret:
        pytest.skip("SUPABASE_JWT_SECRET is not configured; cannot mint a test token")
    if not settings.anthropic_api_key.get_secret_value():
        pytest.skip("ANTHROPIC_API_KEY is not configured")

    candidate_email = f"epic00-{uuid.uuid4()}@example.com"
    token = _mint_bearer_token(jwt_secret, candidate_email)
    http_client = TestClient(create_app())
    application_id: str | None = None

    try:
        # ---- 1. authenticate + write to the DB -----------------------------
        create_response = http_client.post(
            "/api/applications",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "candidate_email": candidate_email,
                "company_name": "Epic 00 Acceptance Co",
                "role_title": "Skeleton Verifier",
                "job_description": (
                    "Prove auth + DB read/write + a routed, cached LLM call "
                    "with cost logging, end to end."
                ),
            },
        )
        assert create_response.status_code == 201, create_response.text
        application_id = create_response.json()["id"]

        # ---- 1. authenticate + read from the DB ----------------------------
        # No query string: the candidate is identified by the token's `email`
        # claim (Epic 07 — no PII in URLs).
        list_response = http_client.get(
            "/api/applications",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_response.status_code == 200
        assert any(a["id"] == application_id for a in list_response.json())

        # The same route must still reject an unauthenticated caller —
        # proving this flow exercises the real auth gate, not a bypass.
        unauthenticated = http_client.get("/api/applications")
        assert unauthenticated.status_code == 401

        # ---- 2/3. routed, cached LLM call with cost logging -----------------
        async with async_session_factory() as session:
            llm_client = AnthropicLlmClient(
                settings,
                usage_logger=SqlAlchemyUsageLogger(session),
                id_generator=UuidIdGenerator(),
            )
            use_case = GetLlmCompletion(llm_client=llm_client)
            dto = LlmCompletionInput(
                prompt="Reply with exactly one word: acknowledged",
                task_type=LlmTaskType.EXTRACTION,  # must route to the cheap tier
                system=_CACHEABLE_SYSTEM_PROMPT,
            )

            with caplog.at_level(
                "INFO", logger="src.infrastructure.llm.anthropic_client"
            ):
                first = await use_case.execute(dto)  # cache write
                second = await use_case.execute(dto)  # cache read

            result = await session.execute(
                select(LlmUsageRecordModel)
                .where(LlmUsageRecordModel.task_type == LlmTaskType.EXTRACTION.value)
                .order_by(LlmUsageRecordModel.created_at.desc())
                .limit(2)
            )
            usage_rows = result.scalars().all()

        assert "acknowledged" in first.text.lower()
        assert "acknowledged" in second.text.lower()

        # 2. prompt caching actually happened: the client logs a cache
        # write on the first call and a cache hit on the second.
        cache_logs = [record.message for record in caplog.records]
        assert any("miss (populated)" in message for message in cache_logs), cache_logs
        assert any(
            message.startswith("anthropic prompt cache hit") for message in cache_logs
        ), cache_logs

        # 2. correct model tier + 3. token/cost logged via the data-access
        # layer (not just stdout) for both calls.
        assert len(usage_rows) == 2
        for row in usage_rows:
            assert row.model_tier == LlmModelTier.CHEAP.value
            assert row.model == settings.anthropic_model_cheap
            assert row.input_tokens > 0
            assert row.output_tokens > 0
            assert row.estimated_cost_usd >= 0
    finally:
        if application_id is not None:
            async with async_session_factory() as session:
                await SqlAlchemyJobApplicationRepository(session).delete(application_id)
        # The two llm_usage_records rows are left in place deliberately —
        # they're the artifact this check exists to prove exists, and
        # `docs/epic-00-acceptance-check.md` documents how to inspect them.
