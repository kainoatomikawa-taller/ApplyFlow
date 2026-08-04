"""Real-database smoke test for the data-rights persistence layer.

Exercises `SqlAlchemyPersonalDataStore` and `SqlAlchemyConsentRepository` against
an actual Postgres connection, end to end: seed a user with data in every store,
export it, erase it, then verify it is gone.

This is the test the acceptance criteria actually rest on. Everything else in the
suite works against fakes, and a fake store cannot fail the way the real one can
— the `RESTRICT` foreign key from `tracked_applications` to
`application_documents` means an erasure in the wrong order raises an integrity
error, and no amount of in-memory testing would show it. Same for the encrypted
columns: an export that could not decrypt them would still be an export, just an
unusable one.

Skips (rather than fails) when no database is reachable, so `pytest` still runs
for contributors without Postgres running locally. Point it at a real one with
`docker compose up db` to have it execute; CI provisions a Postgres service so it
always runs there.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest

from src.application.dtos.data_rights_dtos import (
    DataSubjectRef,
    ErasureRequestInput,
)
from src.application.ports.file_storage_port import FileStoragePort
from src.application.use_cases.erase_user_data import EraseUserData
from src.application.use_cases.export_user_data import ExportUserData
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.entities.resume import Resume
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.services.personal_data_inventory import PERSONAL_DATA_INVENTORY
from src.domain.value_objects.address import Address
from src.domain.value_objects.consent_decision import ConsentDecision
from src.domain.value_objects.consent_purpose import ConsentPurpose
from src.domain.value_objects.eeo_categories import GenderIdentity
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import (
    WorkAuthorizationStatus,
)
from src.infrastructure.persistence.answer_memory_repository_impl import (
    SqlAlchemyAnswerMemoryRepository,
)
from src.infrastructure.persistence.consent_repository_impl import (
    SqlAlchemyConsentRepository,
)
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.persistence.personal_data_store_impl import (
    SqlAlchemyPersonalDataStore,
)
from src.infrastructure.persistence.portal_handoff_repository_impl import (
    SqlAlchemyPortalHandoffRepository,
)
from src.infrastructure.persistence.profile_repository_impl import (
    SqlAlchemyProfileRepository,
)
from src.infrastructure.persistence.resume_repository_impl import (
    SqlAlchemyResumeRepository,
)
from src.infrastructure.security.sensitive_access import SensitiveDataAccess

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
_POLICY = "2026-08-03"


@pytest.fixture(autouse=True)
def _sensitive_access(sensitive_access: SensitiveDataAccess) -> None:
    """Every test here reads encrypted columns — an export reads all of them —
    so the whole module runs inside a sensitive-data access scope, standing in
    for the authorized entry point this code is always called from in production
    (Epic 07). See `tests/conftest.py` for the shared fixture."""


@pytest.fixture
async def schema_ready() -> AsyncIterator[None]:
    # The process-wide engine's pool outlives a test but its connections are
    # bound to the loop that opened them, so a pooled connection from the
    # previous test is unusable here. Disposing on both sides of each test means
    # every one of them opens its own — without it, only the first test in this
    # module would run and the rest would "skip" as unreachable. Same fixture as
    # `test_application_document_persistence_smoke.py`.
    await engine.dispose()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")
    yield
    await engine.dispose()


class _RecordingFileStorage(FileStoragePort):
    """Stands in for the blob store, recording what was deleted.

    A fake rather than a real directory because what is under test is that the
    erasure *reaches* the blob store with the right keys — that the résumé bytes
    are not the one thing left behind. `LocalFileStorage` has its own tests.
    """

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def save(self, storage_key: str, content: bytes) -> None:
        raise AssertionError("the data-rights path never writes files")

    async def delete(self, storage_key: str) -> None:
        self.deleted.append(storage_key)


async def _seed(session: object, user_id: str, email: str) -> dict[str, str]:
    """Give this user a row in every store an erasure has to reach.

    Deliberately includes the special-category tables (work authorization and EEO
    self-identification) and the two free-text stores, because those are the rows
    whose survival would matter most.
    """
    suffix = uuid.uuid4().hex[:8]
    profile = UserProfile(
        id=f"profile-{suffix}",
        user_id=user_id,
        full_name="Smoke Test Person",
        email=EmailAddress(email),
        contact_source=ProvenanceSource.USER_ENTERED,
        phone="+1 555 0100",
        location="Austin, TX",
        address=Address(
            street_address="1 Test Way",
            city="Austin",
            state_or_region="TX",
            postal_code="78701",
            country="USA",
        ),
        address_source=ProvenanceSource.USER_ENTERED,
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id=f"work-{suffix}",
            company_name="Initech",
            job_title="Engineer",
            start_date=date(2020, 1, 1),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    profile.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            citizenship_country="USA",
            source=ProvenanceSource.USER_ENTERED,
        )
    )
    profile.set_eeo_self_identification(
        EeoSelfIdentification(
            gender_identity=GenderIdentity.DECLINE_TO_SELF_IDENTIFY,
            source=ProvenanceSource.USER_ENTERED,
        )
    )
    await SqlAlchemyProfileRepository(session).add(profile)  # type: ignore[arg-type]

    resume = Resume(
        id=f"resume-{suffix}",
        user_id=user_id,
        original_filename="smoke-cv.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_key=f"storage-{suffix}",
        extracted_text="Smoke Test Person — Engineer at Initech.",
    )
    await SqlAlchemyResumeRepository(session).add(resume)  # type: ignore[arg-type]

    await SqlAlchemyAnswerMemoryRepository(session).add(  # type: ignore[arg-type]
        AnswerMemory(
            id=f"answer-{suffix}",
            user_id=user_id,
            question_text="Do you require sponsorship?",
            answer_text="No.",
            embedding=[0.1, 0.2, 0.3],
            source=ProvenanceSource.ANSWER,
        )
    )

    posting = JobPosting(
        id=f"smoke-job-{suffix}",
        source="adzuna",
        company="Smoke Test Co",
        title="Backend Engineer",
        apply_url="https://smoketestco.example.com/careers/privacy",
        description="Build things.",
    )
    await SqlAlchemyJobPostingRepository(session).add(posting)  # type: ignore[arg-type]

    await SqlAlchemyPortalHandoffRepository(session).add(  # type: ignore[arg-type]
        PortalHandoff(
            id=f"handoff-{suffix}",
            user_id=user_id,
            job_posting_id=posting.id,
            apply_url=posting.apply_url,
            paused_url=posting.apply_url,
            hard_stops=(
                HardStop(kind=HardStopKind.CAPTCHA, evidence=("a captcha widget",)),
            ),
        )
    )

    return {"profile_id": profile.id, "storage_key": resume.storage_key}


@pytest.mark.asyncio
async def test_export_then_erase_round_trip_against_a_real_database(
    schema_ready: None,
) -> None:
    user_id = f"smoke-user-{uuid.uuid4()}"
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    subject = DataSubjectRef(user_id=user_id, email=email)
    storage = _RecordingFileStorage()

    async with async_session_factory() as session:
        seeded = await _seed(session, user_id, email)
        consents = SqlAlchemyConsentRepository(session)
        record = await consents.get(
            user_id=user_id, purpose=ConsentPurpose.ANSWER_REUSE
        )
        record.record(
            ConsentDecision(
                purpose=ConsentPurpose.ANSWER_REUSE,
                granted=True,
                decided_at=_NOW,
                policy_version=_POLICY,
            )
        )
        await consents.save(record)

        store = SqlAlchemyPersonalDataStore(session, storage)

        # -- Export: complete, and the sensitive columns came back as plaintext.
        export = await ExportUserData(store=store, consent_repository=consents).execute(
            subject, generated_at=_NOW
        )

        sections = {section.key: section for section in export.categories}
        assert set(sections) == {
            category.key for category in PERSONAL_DATA_INVENTORY.exportable()
        }
        assert export.limitations == (), "an email was supplied; nothing is short"

        profile_rows = sections["profile"].records
        assert any(
            row.get("full_name") == "Smoke Test Person" for row in profile_rows
        ), "encrypted contact details must decrypt into the export"
        assert any(
            row.get("citizenship_country") == "USA" for row in profile_rows
        ), "the special-category tables belong in the export"
        assert any(
            row.get("company_name") == "Initech" for row in profile_rows
        ), "the profile's child tables belong in the export"
        assert (
            sections["resumes"].records[0]["extracted_text"]
            == "Smoke Test Person — Engineer at Initech."
        )
        assert (
            sections["answer_memories"].records[0]["answer_text"] == "No."
        ), "free-text answers must decrypt too"
        assert sections["resume_files"].records[0]["storage_key"] == (
            seeded["storage_key"]
        )
        assert sections["consents"].records[0]["granted"] is True
        assert sections["portal_handoffs"].record_count == 1

        # Timestamps are JSON-safe: a portable copy has to be parseable.
        assert isinstance(sections["resumes"].records[0]["created_at"], str)

        # -- Erase.
        receipt = await EraseUserData(store=store, consent_repository=consents).execute(
            ErasureRequestInput(
                subject=subject,
                requested_at=_NOW,
                acknowledged=True,
                policy_version=_POLICY,
            )
        )

        erased = {category.key: category for category in receipt.erased}
        assert set(erased) == {
            category.key for category in PERSONAL_DATA_INVENTORY.erasable()
        }
        assert erased["profile"].records_erased == 1
        assert erased["resumes"].records_erased == 1
        assert erased["answer_memories"].records_erased == 1
        assert erased["portal_handoffs"].records_erased == 1
        assert storage.deleted == [
            seeded["storage_key"]
        ], "the résumé bytes are the one thing an erasure must not leave behind"
        assert ConsentPurpose.ANSWER_REUSE.value in receipt.consents_withdrawn

        # -- Verify: a second export finds nothing, and the ledger survives.
        after = await ExportUserData(store=store, consent_repository=consents).execute(
            subject, generated_at=_NOW
        )
        remaining = {
            section.key: section.record_count
            for section in after.categories
            if section.record_count
        }
        assert remaining == {"consents": 2}, (
            "everything erasable is gone; the consent ledger is retained as the "
            "record that the erasure was lawful, now holding the grant and the "
            f"withdrawal. Left behind: {remaining}"
        )

        ledger = await consents.get(
            user_id=user_id, purpose=ConsentPurpose.ANSWER_REUSE
        )
        assert not ledger.is_granted
        assert [decision.granted for decision in ledger.history] == [True, False]


@pytest.mark.asyncio
async def test_erasing_a_user_leaves_another_users_data_alone(
    schema_ready: None,
) -> None:
    """The property that has to hold before this application could ever be
    multi-user, asserted now while it is cheap to assert: every query is filtered
    by subject, so an erasure is scoped to one person rather than emptying a
    table.

    At one user this passes trivially. That is the point — it is written now so
    that the day a second user exists, the regression is caught by a test that
    was already there rather than by the first person to lose their data.
    """
    keeper = f"smoke-keeper-{uuid.uuid4()}"
    keeper_email = f"keeper-{uuid.uuid4().hex[:8]}@example.com"
    leaver = f"smoke-leaver-{uuid.uuid4()}"
    leaver_email = f"leaver-{uuid.uuid4().hex[:8]}@example.com"
    storage = _RecordingFileStorage()

    async with async_session_factory() as session:
        keeper_seed = await _seed(session, keeper, keeper_email)
        await _seed(session, leaver, leaver_email)
        store = SqlAlchemyPersonalDataStore(session, storage)
        consents = SqlAlchemyConsentRepository(session)

        await EraseUserData(store=store, consent_repository=consents).execute(
            ErasureRequestInput(
                subject=DataSubjectRef(user_id=leaver, email=leaver_email),
                requested_at=_NOW,
                acknowledged=True,
                policy_version=_POLICY,
            )
        )

        surviving = await ExportUserData(
            store=store, consent_repository=consents
        ).execute(DataSubjectRef(user_id=keeper, email=keeper_email), generated_at=_NOW)
        sections = {section.key: section for section in surviving.categories}
        assert sections["profile"].record_count > 0
        assert sections["resumes"].record_count == 1
        assert sections["answer_memories"].record_count == 1
        assert (
            keeper_seed["storage_key"] not in storage.deleted
        ), "the other user's résumé file must not be deleted"


@pytest.mark.asyncio
async def test_the_consent_ledger_is_append_only_and_ordered(
    schema_ready: None,
) -> None:
    """The ledger's stored form has to survive a round trip in order, because the
    tail is what states the current answer."""
    user_id = f"smoke-consent-{uuid.uuid4()}"

    async with async_session_factory() as session:
        consents = SqlAlchemyConsentRepository(session)

        for granted, at in (
            (True, _NOW),
            (False, datetime(2026, 8, 4, 12, 0, tzinfo=UTC)),
            (True, datetime(2026, 8, 5, 12, 0, tzinfo=UTC)),
        ):
            record = await consents.get(
                user_id=user_id, purpose=ConsentPurpose.AI_DOCUMENT_GENERATION
            )
            record.record(
                ConsentDecision(
                    purpose=ConsentPurpose.AI_DOCUMENT_GENERATION,
                    granted=granted,
                    decided_at=at,
                    policy_version=_POLICY,
                )
            )
            await consents.save(record)

        stored = await consents.get(
            user_id=user_id, purpose=ConsentPurpose.AI_DOCUMENT_GENERATION
        )
        assert [decision.granted for decision in stored.history] == [
            True,
            False,
            True,
        ]
        assert stored.is_granted

        # Re-saving a record that gained nothing writes nothing.
        await consents.save(stored)
        assert (
            len(
                (
                    await consents.get(
                        user_id=user_id, purpose=ConsentPurpose.AI_DOCUMENT_GENERATION
                    )
                ).history
            )
            == 3
        )

        # And every purpose comes back, including the ones never answered.
        all_ledgers = await consents.list_for_user(user_id)
        assert {ledger.purpose for ledger in all_ledgers} == set(ConsentPurpose)
