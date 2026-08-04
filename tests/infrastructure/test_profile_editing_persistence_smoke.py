"""Real-database smoke test for the profile editor's write paths.

Exercises the editor's use cases against an actual Postgres connection: create a
profile from nothing, edit every section, and read it all back — including the two
sensitive records, which is what the whole feature exists to make reachable.

Why this needs a real database rather than the in-memory repository the use-case
tests use: the sensitive columns are encrypted, the two "other names" are new
columns added by migration 0024, and the profile's child tables are written through
SQLAlchemy relationship cascades. All three are places where a mapping can be
wrong in a way no in-memory fake would show.

Skips (rather than fails) when no database is reachable, so `pytest` still runs for
contributors without Postgres locally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest

from src.application.dtos.profile_dtos import (
    AddressInput,
    ContactDetailsInput,
    EeoSelfIdentificationInput,
    QualificationsInput,
    SkillInput,
    WorkAuthorizationInput,
    WorkHistoryInput,
)
from src.application.use_cases.get_profile import GetProfile
from src.application.use_cases.get_work_authorization import GetWorkAuthorization
from src.application.use_cases.remove_skill import RemoveSkill
from src.application.use_cases.save_contact_details import SaveContactDetails
from src.application.use_cases.save_eeo_self_identification import (
    SaveEeoSelfIdentification,
)
from src.application.use_cases.save_skill import SaveSkill
from src.application.use_cases.save_work_authorization import SaveWorkAuthorization
from src.application.use_cases.save_work_history_entry import SaveWorkHistoryEntry
from src.application.use_cases.update_profile_address import UpdateProfileAddress
from src.application.use_cases.update_profile_qualifications import (
    UpdateProfileQualifications,
)
from src.infrastructure.persistence.consent_repository_impl import (
    SqlAlchemyConsentRepository,
)
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.profile_repository_impl import (
    SqlAlchemyProfileRepository,
)
from src.infrastructure.security.sensitive_access import SensitiveDataAccess
from src.infrastructure.services.uuid_id_generator import UuidIdGenerator

_NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
_POLICY = "2026-08-03"


@pytest.fixture(autouse=True)
def _sensitive_access(sensitive_access: SensitiveDataAccess) -> None:
    """Every test here writes and reads encrypted columns — the contact details,
    both name fields, and the two sensitive records — so the whole module runs
    inside an access scope, standing in for the authorized entry point these use
    cases are always called from in production."""


@pytest.fixture
async def schema_ready() -> AsyncIterator[None]:
    # The process-wide engine's pool outlives a test but its connections are bound
    # to the loop that opened them, so a pooled connection from the previous test is
    # unusable here. Same fixture as the other smoke modules.
    await engine.dispose()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_profile_can_be_built_from_nothing_and_edited(
    schema_ready: None,
) -> None:
    """The claim the whole feature rests on: no résumé required.

    Starts with an empty database and a user id, and ends with a complete profile —
    contact details, both other names, an address, a job, a skill, qualifications —
    every one of them typed rather than parsed.
    """
    user_id = f"editor-{uuid.uuid4()}"

    async with async_session_factory() as session:
        profiles = SqlAlchemyProfileRepository(session)
        ids = UuidIdGenerator()

        created = await SaveContactDetails(
            repository=profiles, id_generator=ids
        ).execute(
            ContactDetailsInput(
                user_id=user_id,
                full_name="Michael Andrew Smith",
                email=f"{user_id}@example.com",
                phone="+1 555 0100",
                middle_name="Andrew",
                preferred_name="Mike",
                location="Austin, TX",
            )
        )
        assert created.contact_source == "user_entered"
        assert created.middle_name == "Andrew"
        assert created.preferred_name == "Mike"

        await UpdateProfileAddress(repository=profiles).execute(
            AddressInput(
                user_id=user_id,
                street_address="1 Test Way",
                city="Austin",
                state_or_region="TX",
                postal_code="78701",
                country="USA",
            )
        )
        await SaveWorkHistoryEntry(repository=profiles, id_generator=ids).execute(
            WorkHistoryInput(
                user_id=user_id,
                company_name="Initech",
                job_title="Engineer",
                start_date=date(2020, 1, 1),
            )
        )
        await SaveSkill(repository=profiles, id_generator=ids).execute(
            SkillInput(user_id=user_id, name="Python", proficiency="expert")
        )
        await UpdateProfileQualifications(repository=profiles).execute(
            QualificationsInput(user_id=user_id, highest_degree="masters")
        )

        stored = await GetProfile(repository=profiles).execute(user_id)

    assert stored.full_name == "Michael Andrew Smith"
    assert stored.middle_name == "Andrew"
    assert stored.address is not None
    assert stored.address.city == "Austin"
    assert stored.address.source == "user_entered"
    assert [entry.job_title for entry in stored.work_history] == ["Engineer"]
    assert [skill.name for skill in stored.skills] == ["Python"]
    assert stored.qualifications is not None
    assert stored.qualifications.highest_degree == "masters"


@pytest.mark.asyncio
async def test_work_authorization_round_trips_and_is_attested(
    schema_ready: None,
) -> None:
    """The hole-closer, against a real database.

    `is_candidate_attested` is the assertion that matters: it is what
    `decide_sensitive_field` requires before a value may be put on an application,
    and it survives the encrypted round trip rather than only holding in memory.
    """
    user_id = f"editor-{uuid.uuid4()}"

    async with async_session_factory() as session:
        profiles = SqlAlchemyProfileRepository(session)
        consents = SqlAlchemyConsentRepository(session)
        await SaveContactDetails(
            repository=profiles, id_generator=UuidIdGenerator()
        ).execute(
            ContactDetailsInput(
                user_id=user_id,
                full_name="Dana Reyes",
                email=f"{user_id}@example.com",
            )
        )

        saved = await SaveWorkAuthorization(
            profile_repository=profiles, consent_repository=consents
        ).execute(
            WorkAuthorizationInput(
                user_id=user_id,
                status="visa_holder",
                citizenship_country="Nigeria",
                visa_type="H-1B",
                requires_sponsorship=True,
                consent_acknowledged=True,
            ),
            decided_at=_NOW,
            policy_version=_POLICY,
        )
        assert saved.is_candidate_attested
        assert saved.consent_granted

        read_back = await GetWorkAuthorization(
            profile_repository=profiles, consent_repository=consents
        ).execute(user_id)

    assert read_back.status == "visa_holder"
    assert read_back.citizenship_country == "Nigeria"
    assert read_back.visa_type == "H-1B"
    # The field that a bad mapping turns from an exact "No" into a refusal.
    assert read_back.requires_sponsorship is True
    assert read_back.is_candidate_attested
    assert read_back.source == "user_entered"


@pytest.mark.asyncio
async def test_sponsorship_false_survives_the_round_trip(schema_ready: None) -> None:
    """`False` is the value most easily lost. It is an encrypted boolean, and a
    mapping that turned it into `None` would silently downgrade an exact "I do not
    need sponsorship" into "the record does not say" — which surfaces the question
    instead of answering it."""
    user_id = f"editor-{uuid.uuid4()}"

    async with async_session_factory() as session:
        profiles = SqlAlchemyProfileRepository(session)
        consents = SqlAlchemyConsentRepository(session)
        await SaveContactDetails(
            repository=profiles, id_generator=UuidIdGenerator()
        ).execute(
            ContactDetailsInput(
                user_id=user_id,
                full_name="Dana Reyes",
                email=f"{user_id}@example.com",
            )
        )
        await SaveWorkAuthorization(
            profile_repository=profiles, consent_repository=consents
        ).execute(
            WorkAuthorizationInput(
                user_id=user_id,
                status="citizen",
                requires_sponsorship=False,
                consent_acknowledged=True,
            ),
            decided_at=_NOW,
            policy_version=_POLICY,
        )
        read_back = await GetWorkAuthorization(
            profile_repository=profiles, consent_repository=consents
        ).execute(user_id)

    assert read_back.requires_sponsorship is False


@pytest.mark.asyncio
async def test_the_eeo_record_round_trips_and_can_be_withdrawn(
    schema_ready: None,
) -> None:
    """Including the distinction that matters most in this record: a declined
    category is an *answer* and survives as one, while an unanswered category stays
    absent."""
    user_id = f"editor-{uuid.uuid4()}"

    async with async_session_factory() as session:
        profiles = SqlAlchemyProfileRepository(session)
        consents = SqlAlchemyConsentRepository(session)
        await SaveContactDetails(
            repository=profiles, id_generator=UuidIdGenerator()
        ).execute(
            ContactDetailsInput(
                user_id=user_id,
                full_name="Dana Reyes",
                email=f"{user_id}@example.com",
            )
        )
        use_case = SaveEeoSelfIdentification(
            profile_repository=profiles, consent_repository=consents
        )

        stored = await use_case.execute(
            EeoSelfIdentificationInput(
                user_id=user_id,
                gender_identity="decline_to_self_identify",
                veteran_status="protected_veteran",
                consent_acknowledged=True,
            ),
            decided_at=_NOW,
            policy_version=_POLICY,
        )
        assert stored.gender_identity == "decline_to_self_identify"
        assert stored.veteran_status == "protected_veteran"
        assert stored.race_ethnicity is None, "unanswered is not the same as declined"

        cleared = await use_case.execute(
            EeoSelfIdentificationInput(user_id=user_id),
            decided_at=_NOW,
            policy_version=_POLICY,
        )

    assert cleared.gender_identity is None
    assert cleared.source is None
    # Deleting the data does not revoke the permission to hold it.
    assert cleared.consent_granted


@pytest.mark.asyncio
async def test_a_skill_can_be_removed_after_being_added(schema_ready: None) -> None:
    """Delete against a real database, because the child rows go through a
    relationship cascade rather than an explicit delete."""
    user_id = f"editor-{uuid.uuid4()}"

    async with async_session_factory() as session:
        profiles = SqlAlchemyProfileRepository(session)
        ids = UuidIdGenerator()
        await SaveContactDetails(repository=profiles, id_generator=ids).execute(
            ContactDetailsInput(
                user_id=user_id,
                full_name="Dana Reyes",
                email=f"{user_id}@example.com",
            )
        )
        with_skill = await SaveSkill(repository=profiles, id_generator=ids).execute(
            SkillInput(user_id=user_id, name="Rust")
        )
        skill_id = with_skill.skills[0].id

        after = await RemoveSkill(repository=profiles).execute(user_id, skill_id)

    assert after.skills == []
