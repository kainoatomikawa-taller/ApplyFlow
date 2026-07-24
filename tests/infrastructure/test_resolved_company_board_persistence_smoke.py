"""Real-database smoke test for the resolved-company-board cache
persistence layer.

Exercises `SqlAlchemyResolvedCompanyBoardRepository` against an actual
Postgres connection end to end: save -> read by normalized company.
Mirrors `test_job_posting_persistence_smoke.py`.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid

import pytest

from src.domain.entities.resolved_company_board import ResolvedCompanyBoard
from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.resolved_company_board_repository_impl import (
    SqlAlchemyResolvedCompanyBoardRepository,
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
    board = ResolvedCompanyBoard(
        company=unique_company,
        provider=AtsProvider.GREENHOUSE,
        board_token="smoke-test-co",
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyResolvedCompanyBoardRepository(session)
        await repository.save(board)

        fetched = await repository.get_by_normalized_company(
            board.normalized_company
        )
        assert fetched is not None
        assert fetched.company == unique_company
        assert fetched.provider == AtsProvider.GREENHOUSE
        assert fetched.board_token == "smoke-test-co"

        miss = await repository.get_by_normalized_company(
            "a company that has never been resolved"
        )
        assert miss is None
