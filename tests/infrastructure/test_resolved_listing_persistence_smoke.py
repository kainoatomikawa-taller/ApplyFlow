"""Real-database smoke test for the resolved-listing cache persistence
layer.

Exercises `SqlAlchemyResolvedListingRepository` against an actual Postgres
connection end to end: save -> read by normalized company. Mirrors
`test_job_posting_persistence_smoke.py`.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid

import pytest

from src.domain.entities.resolved_listing import ResolvedListing
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.resolved_listing_repository_impl import (
    SqlAlchemyResolvedListingRepository,
)


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


@pytest.mark.asyncio
async def test_save_and_read_round_trip_against_a_real_database(
    schema_ready: None,
) -> None:
    unique_company = f"Smoke Test Co {uuid.uuid4()}"
    resolved = ResolvedListing(
        company=unique_company,
        apply_url="https://smoketestco.example.com/careers",
        description="Smoke Test Co's official careers page.",
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyResolvedListingRepository(session)
        await repository.save(resolved)

        fetched = await repository.get_by_normalized_company(
            resolved.normalized_company
        )
        assert fetched is not None
        assert fetched.company == unique_company
        assert fetched.apply_url == "https://smoketestco.example.com/careers"
        assert fetched.description == "Smoke Test Co's official careers page."

        miss = await repository.get_by_normalized_company(
            "a company that has never been resolved"
        )
        assert miss is None
