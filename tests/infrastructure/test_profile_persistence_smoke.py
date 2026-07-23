"""Real-database smoke test for the profile persistence layer.

Exercises `SqlAlchemyProfileRepository` against an actual Postgres
connection end to end: create a full profile (work history, education,
skills, address, links) -> read it back by id and by user_id -> update it
(including setting and then clearing the sensitive work-authorization/EEO
fields) -> delete it -> verify gone. Mirrors `test_persistence_smoke.py`.

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
from src.domain.value_objects.address import Address
from src.domain.value_objects.eeo_categories import (
    DisabilityStatus,
    GenderIdentity,
    RaceEthnicity,
    VeteranStatus,
)
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)
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
    profile.set_address(
        Address(
            street_address="123 Main St",
            city="Springfield",
            state_or_region="IL",
            postal_code="62701",
            country="USA",
        )
    )
    profile.set_links(
        ProfileLinks(
            portfolio_url="https://jane.dev",
            linkedin_url="https://www.linkedin.com/in/janedoe",
            github_url="https://github.com/janedoe",
        )
    )
    profile.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.VISA_HOLDER,
            citizenship_country="Canada",
            visa_type="H-1B",
            requires_sponsorship=True,
        )
    )
    # eeo_self_identification is deliberately left unset here — see the
    # assertion below proving a full profile still never defaults it.
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

            # Contact info + links round-trip.
            assert fetched.address.city == "Springfield"
            assert fetched.address.country == "USA"
            assert fetched.links.github_url == "https://github.com/janedoe"

            # Sensitive: work authorization round-trips...
            assert fetched.work_authorization is not None
            assert fetched.work_authorization.status is (
                WorkAuthorizationStatus.VISA_HOLDER
            )
            assert fetched.work_authorization.visa_type == "H-1B"
            assert fetched.work_authorization.requires_sponsorship is True

            # ...while EEO self-ID is never defaulted: even on a profile
            # with every other field populated, it stays None until a
            # candidate explicitly provides it.
            assert fetched.eeo_self_identification is None

            by_user = await repository.get_by_user_id(user_id)
            assert by_user is not None
            assert by_user.id == profile.id

            # Update: drop one skill, add a new work history entry, and
            # exercise the sensitive fields' explicit set/clear path.
            fetched.skills = [s for s in fetched.skills if s.name != "SQL"]
            fetched.add_work_history(
                WorkHistoryEntry(
                    id=f"wh-{uuid.uuid4()}",
                    company_name="Another Co",
                    job_title="Staff Engineer",
                    start_date=date(2024, 1, 1),
                )
            )
            fetched.set_eeo_self_identification(
                EeoSelfIdentification(
                    gender_identity=GenderIdentity.DECLINE_TO_SELF_IDENTIFY,
                    race_ethnicity=RaceEthnicity.DECLINE_TO_SELF_IDENTIFY,
                    veteran_status=VeteranStatus.NOT_A_PROTECTED_VETERAN,
                    disability_status=DisabilityStatus.NO_DISABILITY,
                )
            )
            fetched.set_work_authorization(None)  # candidate withdraws it
            await repository.update(fetched)

            updated = await repository.get_by_id(profile.id)
            assert updated is not None
            assert len(updated.work_history) == 3
            assert len(updated.skills) == 1
            assert updated.skills[0].name == "Python"
            assert updated.work_authorization is None
            assert updated.eeo_self_identification is not None
            assert updated.eeo_self_identification.gender_identity is (
                GenderIdentity.DECLINE_TO_SELF_IDENTIFY
            )
            assert updated.eeo_self_identification.disability_status is (
                DisabilityStatus.NO_DISABILITY
            )
        finally:
            await repository.delete(profile.id)

        deleted = await repository.get_by_id(profile.id)
        assert deleted is None
