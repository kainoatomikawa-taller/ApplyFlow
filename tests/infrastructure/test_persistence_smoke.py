"""Real-database smoke test for the persistence layer.

Exercises `SqlAlchemyJobApplicationRepository` against an actual Postgres
connection end to end: create -> read -> delete -> verify gone. This is
the one test in the suite that talks to a real database rather than an
in-memory fake, proving the pool/session wiring in
`src/infrastructure/persistence/database.py` actually works.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally. Point it at a real
one with `docker compose up db` (or any Postgres matching `DATABASE_URL`)
to have it execute; CI provisions a Postgres service so it always runs there.
"""

from __future__ import annotations

import uuid

import pytest

from src.domain.entities.job_application import JobApplication
from src.domain.value_objects.email_address import EmailAddress
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.job_application_repository_impl import (
    SqlAlchemyJobApplicationRepository,
)


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


@pytest.mark.asyncio
async def test_create_read_delete_round_trip_against_a_real_database(
    schema_ready: None,
) -> None:
    application = JobApplication(
        id=f"smoke-{uuid.uuid4()}",
        candidate_email=EmailAddress("smoke-test@example.com"),
        company_name="Smoke Test Co",
        role_title="QA Engineer",
        job_description="Prove the persistence layer works end to end.",
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyJobApplicationRepository(session)
        await repository.add(application)

        try:
            fetched = await repository.get_by_id(application.id)
            assert fetched is not None
            assert fetched.id == application.id
            assert str(fetched.candidate_email) == "smoke-test@example.com"
            assert fetched.company_name == "Smoke Test Co"
            assert fetched.role_title == "QA Engineer"
        finally:
            await repository.delete(application.id)

        deleted = await repository.get_by_id(application.id)
        assert deleted is None
