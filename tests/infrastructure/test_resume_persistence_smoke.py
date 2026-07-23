"""Real-database smoke test for the resume persistence layer.

Exercises `SqlAlchemyResumeRepository` against an actual Postgres
connection end to end: create -> read by id -> list by user -> delete ->
verify gone. Mirrors `test_persistence_smoke.py`.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid

import pytest

from src.domain.entities.resume import Resume
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.resume_repository_impl import (
    SqlAlchemyResumeRepository,
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
    resume = Resume(
        id=f"smoke-resume-{uuid.uuid4()}",
        user_id=user_id,
        original_filename="jane-doe-resume.pdf",
        content_type="application/pdf",
        size_bytes=2048,
        storage_key=f"smoke-storage-{uuid.uuid4()}",
        extracted_text="Jane Doe. Senior Software Engineer.",
    )

    async with async_session_factory() as session:
        repository = SqlAlchemyResumeRepository(session)
        await repository.add(resume)

        try:
            fetched = await repository.get_by_id(resume.id)
            assert fetched is not None
            assert fetched.user_id == user_id
            assert fetched.original_filename == "jane-doe-resume.pdf"
            assert fetched.content_type == "application/pdf"
            assert fetched.size_bytes == 2048
            assert fetched.extracted_text == "Jane Doe. Senior Software Engineer."

            by_user = await repository.list_by_user_id(user_id)
            assert [r.id for r in by_user] == [resume.id]
        finally:
            await repository.delete(resume.id)

        deleted = await repository.get_by_id(resume.id)
        assert deleted is None
        assert await repository.list_by_user_id(user_id) == []
