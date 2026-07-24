"""Real-database smoke test for the answer-memory persistence layer.

Exercises `SqlAlchemyAnswerMemoryRepository` against an actual Postgres
connection end to end: create -> read by id -> list by user -> delete ->
verify gone. Mirrors `test_resume_persistence_smoke.py`.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid

import pytest

from src.domain.entities.answer_memory import AnswerMemory
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.infrastructure.persistence.answer_memory_repository_impl import (
    SqlAlchemyAnswerMemoryRepository,
)
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


@pytest.mark.asyncio
async def test_create_read_list_delete_round_trip_against_a_real_database(
    schema_ready: None,
) -> None:
    user_id = f"smoke-user-{uuid.uuid4()}"
    answer_memory = AnswerMemory(
        id=f"smoke-answer-{uuid.uuid4()}",
        user_id=user_id,
        question_text="Are you willing to relocate?",
        answer_text="Yes, within the US.",
        embedding=[0.1, 0.2, 0.3],
        source=ProvenanceSource.ANSWER,
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyAnswerMemoryRepository(session)
        await repository.add(answer_memory)

        try:
            fetched = await repository.get_by_id(answer_memory.id)
            assert fetched is not None
            assert fetched.user_id == user_id
            assert fetched.question_text == "Are you willing to relocate?"
            assert fetched.answer_text == "Yes, within the US."
            assert fetched.embedding == [0.1, 0.2, 0.3]
            assert fetched.source is ProvenanceSource.ANSWER

            by_user = await repository.list_by_user_id(user_id)
            assert [a.id for a in by_user] == [answer_memory.id]
        finally:
            await repository.delete(answer_memory.id)

        deleted = await repository.get_by_id(answer_memory.id)
        assert deleted is None
        assert await repository.list_by_user_id(user_id) == []
