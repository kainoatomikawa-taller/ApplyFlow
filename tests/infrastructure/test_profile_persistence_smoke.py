"""Real-database smoke test for the profile persistence layer.

Exercises `SqlAlchemyProfileRepository` against an actual Postgres
connection end to end: create a full profile (work history, education,
skills) -> read it back by id and by user_id -> update it -> delete it ->
verify gone. Mirrors `test_persistence_smoke.py`.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.profile_repository_impl import (
    SqlAlchemyProfileRepository,
)


@pytest.fixture
async def schema_ready() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")


def _full_profile(user_id: str) -> UserProfile:
    profile = UserProfile(
        id=f"smoke-profile-{uuid.uuid4()}",
        user_id=user_id,
        full_name="Smoke Test Candidate",
        email=EmailAddress("smoke-test@example.com"),
        phone="+1-555-0100",
        headline="Senior QA Engineer",
        location="Remote",
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id=f"wh-{uuid.uuid4()}",
            company_name="Smoke Test Co",
            job_title="QA Engineer",
            start_date=date(2020, 1, 1),
            end_date=date(2022, 6, 30),
            location="Remote",
            description="Proved things work end to end.",
        )
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id=f"wh-{uuid.uuid4()}",
            company_name="Persistence Layer Inc",
            job_title="Senior QA Engineer",
            start_date=date(2022, 7, 1),
        )
    )
    profile.add_education(
        EducationEntry(
            id=f"ed-{uuid.uuid4()}",
            institution_name="State University",
            degree="B.S. Computer Science",
            field_of_study="Computer Science",
            start_date=date(2016, 9, 1),
            end_date=date(2020, 5, 1),
        )
    )
    profile.add_skill(
        Skill(
            id=f"sk-{uuid.uuid4()}",
            name="Python",
            proficiency=ProficiencyLevel.EXPERT,
            years_of_experience=6,
        )
    )
    profile.add_skill(Skill(id=f"sk-{uuid.uuid4()}", name="SQL"))
    return profile


@pytest.mark.asyncio
async def test_create_read_full_profile_round_trip_against_a_real_database(
    schema_ready: None,
) -> None:
    user_id = f"smoke-user-{uuid.uuid4()}"
    profile = _full_profile(user_id)

    async with async_session_factory() as session:
        repository = SqlAlchemyProfileRepository(session)
        await repository.add(profile)

        try:
            fetched = await repository.get_by_id(profile.id)
            assert fetched is not None
            assert fetched.user_id == user_id
            assert fetched.full_name == "Smoke Test Candidate"
            assert str(fetched.email) == "smoke-test@example.com"
            assert len(fetched.work_history) == 2
            assert len(fetched.education) == 1
            assert len(fetched.skills) == 2
            assert {s.name for s in fetched.skills} == {"Python", "SQL"}
            python_skill = next(s for s in fetched.skills if s.name == "Python")
            assert python_skill.proficiency is ProficiencyLevel.EXPERT
            assert python_skill.years_of_experience == 6

            by_user = await repository.get_by_user_id(user_id)
            assert by_user is not None
            assert by_user.id == profile.id

            # Update: drop one skill, add a new work history entry.
            fetched.skills = [s for s in fetched.skills if s.name != "SQL"]
            fetched.add_work_history(
                WorkHistoryEntry(
                    id=f"wh-{uuid.uuid4()}",
                    company_name="Another Co",
                    job_title="Staff Engineer",
                    start_date=date(2024, 1, 1),
                )
            )
            await repository.update(fetched)

            updated = await repository.get_by_id(profile.id)
            assert updated is not None
            assert len(updated.work_history) == 3
            assert len(updated.skills) == 1
            assert updated.skills[0].name == "Python"
        finally:
            await repository.delete(profile.id)

        deleted = await repository.get_by_id(profile.id)
        assert deleted is None
