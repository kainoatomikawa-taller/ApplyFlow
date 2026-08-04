"""Tests for the data-subject rights use cases: export, erasure, and consent.

The fakes here are deliberately not "a store that returns what I want". The store
double is driven by the *real* inventory, because what these use cases are for is
holding the answer to the inventory's shape — an export that quietly skipped a
category, or an erasure that reported success over a category nothing touched,
are the two failures worth having tests for, and a hand-picked fake would make
both invisible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from src.application.dtos.data_rights_dtos import (
    DataSubjectRef,
    ErasureRequestInput,
    PersonalDataRecord,
    RecordConsentInput,
)
from src.application.exceptions import (
    ErasureNotAcknowledgedError,
    PersonalDataCoverageError,
    UnknownConsentPurposeError,
)
from src.application.mappers.consent_mapper import ConsentMapper
from src.application.ports.personal_data_store_port import PersonalDataStorePort
from src.application.use_cases.erase_user_data import EraseUserData
from src.application.use_cases.export_user_data import ExportUserData
from src.application.use_cases.list_user_consents import ListUserConsents
from src.application.use_cases.record_consent import RecordConsent
from src.domain.entities.consent_record import ConsentRecord
from src.domain.exceptions import ConsentNotWithdrawableError
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.services.personal_data_inventory import PERSONAL_DATA_INVENTORY
from src.domain.value_objects.consent_purpose import ConsentPurpose

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
_POLICY = "2026-08-03"
_SUBJECT = DataSubjectRef(user_id="user-1", email="dev@example.com")


class _FakePersonalDataStore(PersonalDataStorePort):
    """A store that answers for every category the inventory declares.

    `omit` drops a category from the answer, standing in for the two real ways
    that happens: an inventory entry added without a handler, and an adapter
    returning a partial mapping.
    """

    def __init__(
        self,
        *,
        records: Mapping[str, int] | None = None,
        omit: frozenset[str] = frozenset(),
    ) -> None:
        self._records = dict(records or {})
        self._omit = omit
        self.read_keys: list[str] = []
        self.erased_keys: list[str] = []

    def handled_categories(self) -> frozenset[str]:
        return (
            frozenset(c.key for c in PERSONAL_DATA_INVENTORY.needing_local_handler())
            - self._omit
        )

    async def read(
        self, *, subject: DataSubjectRef, category_keys: Sequence[str]
    ) -> Mapping[str, tuple[PersonalDataRecord, ...]]:
        self.read_keys = list(category_keys)
        return {
            key: tuple(
                {"id": f"{key}-{index}", "user_id": subject.user_id}
                for index in range(self._records.get(key, 0))
            )
            for key in category_keys
            if key not in self._omit
        }

    async def erase(
        self, *, subject: DataSubjectRef, category_keys: Sequence[str]
    ) -> Mapping[str, int]:
        self.erased_keys = list(category_keys)
        return {
            key: self._records.get(key, 0)
            for key in category_keys
            if key not in self._omit
        }


class _InMemoryConsentRepository(ConsentRepository):
    def __init__(self) -> None:
        self._records: dict[tuple[str, ConsentPurpose], ConsentRecord] = {}

    async def get(self, *, user_id: str, purpose: ConsentPurpose) -> ConsentRecord:
        stored = self._records.get((user_id, purpose))
        return ConsentRecord(
            user_id=user_id,
            purpose=purpose,
            history=stored.history if stored else (),
        )

    async def list_for_user(self, user_id: str) -> list[ConsentRecord]:
        return [
            await self.get(user_id=user_id, purpose=purpose)
            for purpose in ConsentPurpose
        ]

    async def save(self, record: ConsentRecord) -> None:
        self._records[(record.user_id, record.purpose)] = record


# -- Export ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_export_asks_for_every_exportable_category_and_no_other() -> None:
    """The category list comes from the inventory, not from the adapter, so an
    adapter cannot smuggle a section in or drop one out."""
    store = _FakePersonalDataStore()
    use_case = ExportUserData(
        store=store, consent_repository=_InMemoryConsentRepository()
    )

    output = await use_case.execute(_SUBJECT, generated_at=_NOW)

    expected = [c.key for c in PERSONAL_DATA_INVENTORY.exportable()]
    assert store.read_keys == expected
    assert [category.key for category in output.categories] == expected


@pytest.mark.asyncio
async def test_the_export_carries_the_records_and_their_lawful_basis() -> None:
    store = _FakePersonalDataStore(records={"resumes": 2, "answer_memories": 3})
    use_case = ExportUserData(
        store=store, consent_repository=_InMemoryConsentRepository()
    )

    output = await use_case.execute(_SUBJECT, generated_at=_NOW)
    sections = {category.key: category for category in output.categories}

    assert sections["resumes"].record_count == 2
    assert len(sections["resumes"].records) == 2
    assert sections["answer_memories"].lawful_basis == "consent"
    assert sections["profile"].record_count == 0, "empty is not missing"
    assert output.generated_at == _NOW
    assert output.format_version


@pytest.mark.asyncio
async def test_the_export_names_the_categories_it_cannot_include() -> None:
    """The gaps in the compliance story, in the document the user receives. The
    processor and the employer are the ones a user could not otherwise know
    about."""
    use_case = ExportUserData(
        store=_FakePersonalDataStore(),
        consent_repository=_InMemoryConsentRepository(),
    )

    output = await use_case.execute(_SUBJECT, generated_at=_NOW)
    deferred = {category.key: category for category in output.deferred_categories}

    assert "model_provider_processing" in deferred
    assert "employer_disclosures" in deferred
    assert "application_logs" in deferred
    for category in output.deferred_categories:
        assert category.note.strip(), category.key


@pytest.mark.asyncio
async def test_an_export_missing_a_declared_category_is_refused() -> None:
    """A copy short by one section is indistinguishable from a copy of someone
    who had no data in it, so it is not delivered at all."""
    use_case = ExportUserData(
        store=_FakePersonalDataStore(omit=frozenset({"answer_memories"})),
        consent_repository=_InMemoryConsentRepository(),
    )

    with pytest.raises(PersonalDataCoverageError) as excinfo:
        await use_case.execute(_SUBJECT, generated_at=_NOW)
    assert excinfo.value.missing == ("answer_memories",)


@pytest.mark.asyncio
async def test_the_export_includes_the_consent_state_and_the_full_history() -> None:
    repository = _InMemoryConsentRepository()
    await RecordConsent(repository).execute(
        RecordConsentInput(
            user_id="user-1",
            purpose="answer_reuse",
            granted=True,
            decided_at=_NOW,
            policy_version=_POLICY,
        )
    )
    await RecordConsent(repository).execute(
        RecordConsentInput(
            user_id="user-1",
            purpose="answer_reuse",
            granted=False,
            decided_at=_NOW + timedelta(hours=1),
            policy_version=_POLICY,
        )
    )

    output = await ExportUserData(
        store=_FakePersonalDataStore(), consent_repository=repository
    ).execute(_SUBJECT, generated_at=_NOW)

    states = {state.purpose: state for state in output.consents}
    assert set(states) == {purpose.value for purpose in ConsentPurpose}
    assert not states["answer_reuse"].granted
    assert states["answer_reuse"].decided
    # The grant survives the withdrawal — the point of a ledger.
    reuse_history = [
        decision
        for decision in output.consent_history
        if decision.purpose == "answer_reuse"
    ]
    assert [decision.granted for decision in reuse_history] == [True, False]
    assert output.consent_policy_version == _POLICY


@pytest.mark.asyncio
async def test_an_export_without_an_email_reports_the_store_it_could_not_search() -> (
    None
):
    """Reporting an empty section would read as "you had none". The limitation is
    stated in the document because the person holding it is the one who needs to
    know it may be short."""
    output = await ExportUserData(
        store=_FakePersonalDataStore(), consent_repository=_InMemoryConsentRepository()
    ).execute(DataSubjectRef(user_id="user-1"), generated_at=_NOW)

    assert any("legacy_applications" in note for note in output.limitations)


# -- Erasure -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_erasure_deletes_every_erasable_category_and_reports_the_counts() -> None:
    store = _FakePersonalDataStore(records={"resumes": 2, "tracked_applications": 5})
    use_case = EraseUserData(
        store=store, consent_repository=_InMemoryConsentRepository()
    )

    output = await use_case.execute(_acknowledged_request())

    assert store.erased_keys == [c.key for c in PERSONAL_DATA_INVENTORY.erasable()]
    assert output.total_records_erased == 7
    erased = {category.key: category for category in output.erased}
    assert erased["resumes"].records_erased == 2
    assert "resume_files" in erased, "the blob store is part of an erasure"


@pytest.mark.asyncio
async def test_erasure_never_asks_the_store_to_delete_the_consent_ledger() -> None:
    """The retained category. Asserted from the caller's side as well as the
    adapter's, because two independent things have to hold: the store cannot
    delete it, and nothing asks."""
    store = _FakePersonalDataStore()
    await EraseUserData(
        store=store, consent_repository=_InMemoryConsentRepository()
    ).execute(_acknowledged_request())

    assert "consents" not in store.erased_keys


@pytest.mark.asyncio
async def test_erasure_withdraws_the_consents_that_were_actually_in_effect() -> None:
    """Recorded before the deletion, so the retained ledger shows the request
    being honored rather than an account that merely stopped existing."""
    repository = _InMemoryConsentRepository()
    await RecordConsent(repository).execute(_consent_input(purpose="answer_reuse"))

    output = await EraseUserData(
        store=_FakePersonalDataStore(), consent_repository=repository
    ).execute(_acknowledged_request(at=_NOW + timedelta(hours=1)))

    assert output.consents_withdrawn == ("answer_reuse",)
    record = await repository.get(user_id="user-1", purpose=ConsentPurpose.ANSWER_REUSE)
    assert not record.is_granted
    assert [decision.granted for decision in record.history] == [True, False]


@pytest.mark.asyncio
async def test_erasure_writes_no_withdrawal_for_a_consent_never_given() -> None:
    """A purpose the user never granted is already denied by default. Appending
    "withdrawn" would record a decision nobody made and leave the retained
    ledger full of entries that demonstrate nothing."""
    repository = _InMemoryConsentRepository()
    output = await EraseUserData(
        store=_FakePersonalDataStore(), consent_repository=repository
    ).execute(_acknowledged_request())

    assert output.consents_withdrawn == ()
    for purpose in ConsentPurpose:
        record = await repository.get(user_id="user-1", purpose=purpose)
        assert record.history == ()


@pytest.mark.asyncio
async def test_erasure_never_withdraws_a_contract_based_purpose() -> None:
    """The erasure *is* how that processing stops, so a ledger entry claiming the
    user switched it off would misdescribe what happened."""
    repository = _InMemoryConsentRepository()
    await RecordConsent(repository).execute(
        _consent_input(purpose="account_and_applications")
    )

    output = await EraseUserData(
        store=_FakePersonalDataStore(), consent_repository=repository
    ).execute(_acknowledged_request(at=_NOW + timedelta(hours=1)))

    assert ConsentPurpose.ACCOUNT_AND_APPLICATIONS.value not in (
        output.consents_withdrawn
    )
    record = await repository.get(
        user_id="user-1", purpose=ConsentPurpose.ACCOUNT_AND_APPLICATIONS
    )
    assert [decision.granted for decision in record.history] == [True]


@pytest.mark.asyncio
async def test_erasure_reports_what_it_retained_and_why() -> None:
    """A receipt listing only deletions invites the reader to conclude the
    remainder was nothing."""
    output = await EraseUserData(
        store=_FakePersonalDataStore(), consent_repository=_InMemoryConsentRepository()
    ).execute(_acknowledged_request())

    retained = {category.key: category for category in output.retained}
    assert "consents" in retained
    assert "7(1)" in retained["consents"].note
    assert "employer_disclosures" in retained
    for category in output.retained:
        assert category.note.strip(), category.key


@pytest.mark.asyncio
async def test_an_unacknowledged_erasure_is_refused() -> None:
    """Irreversible and total: an endpoint that ran on an empty body is one an
    accidental POST can trigger. Enforced in the use case so every adapter
    inherits it."""
    store = _FakePersonalDataStore()
    with pytest.raises(ErasureNotAcknowledgedError):
        await EraseUserData(
            store=store, consent_repository=_InMemoryConsentRepository()
        ).execute(_acknowledged_request(acknowledged=False))
    assert store.erased_keys == [], "nothing may be touched before the check"


@pytest.mark.asyncio
async def test_an_erasure_missing_a_declared_category_is_refused() -> None:
    """Half an erasure is worse than a failed one: only the failure tells anyone
    to try again."""
    use_case = EraseUserData(
        store=_FakePersonalDataStore(omit=frozenset({"portal_handoffs"})),
        consent_repository=_InMemoryConsentRepository(),
    )
    with pytest.raises(PersonalDataCoverageError) as excinfo:
        await use_case.execute(_acknowledged_request())
    assert excinfo.value.missing == ("portal_handoffs",)


@pytest.mark.asyncio
async def test_a_second_erasure_appends_no_duplicate_withdrawals() -> None:
    """The ledger is already withdrawn, so there is nothing left to withdraw and
    the second receipt names nothing."""
    repository = _InMemoryConsentRepository()
    await RecordConsent(repository).execute(_consent_input())
    use_case = EraseUserData(
        store=_FakePersonalDataStore(), consent_repository=repository
    )

    await use_case.execute(_acknowledged_request(at=_NOW + timedelta(hours=1)))
    second = await use_case.execute(_acknowledged_request(at=_NOW + timedelta(days=1)))

    assert second.consents_withdrawn == ()
    record = await repository.get(user_id="user-1", purpose=ConsentPurpose.ANSWER_REUSE)
    assert len(record.history) == 2


@pytest.mark.asyncio
async def test_an_erasure_without_an_email_reports_what_it_could_not_reach() -> None:
    output = await EraseUserData(
        store=_FakePersonalDataStore(), consent_repository=_InMemoryConsentRepository()
    ).execute(_acknowledged_request(subject=DataSubjectRef(user_id="user-1")))

    assert any("legacy_applications" in note for note in output.limitations)


# -- Consent -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_consent_reports_whether_the_ledger_changed() -> None:
    repository = _InMemoryConsentRepository()
    use_case = RecordConsent(repository)

    first = await use_case.execute(_consent_input())
    assert first.changed
    assert first.state.granted

    again = await use_case.execute(_consent_input(at=_NOW + timedelta(minutes=5)))
    assert not again.changed, "a re-sent toggle is not a new decision"
    assert again.state.granted


@pytest.mark.asyncio
async def test_withdrawing_a_contract_based_purpose_is_refused() -> None:
    with pytest.raises(ConsentNotWithdrawableError):
        await RecordConsent(_InMemoryConsentRepository()).execute(
            _consent_input(purpose="account_and_applications", granted=False)
        )


@pytest.mark.asyncio
async def test_an_unknown_purpose_names_the_ones_that_exist() -> None:
    with pytest.raises(UnknownConsentPurposeError) as excinfo:
        await RecordConsent(_InMemoryConsentRepository()).execute(
            _consent_input(purpose="sell_my_data")
        )
    assert "answer_reuse" in str(excinfo.value)


@pytest.mark.asyncio
async def test_listing_consents_returns_every_purpose_including_unanswered() -> None:
    """A purpose added by a release shows up as undecided rather than missing."""
    states = await ListUserConsents(_InMemoryConsentRepository()).execute("user-1")

    assert {state.purpose for state in states} == {p.value for p in ConsentPurpose}
    for state in states:
        assert not state.decided
        assert state.description.strip()


def test_every_purpose_has_user_facing_text() -> None:
    """Consent that is not informed is not consent, so a purpose with no
    description cannot be asked about. Adding a purpose has to add its text."""
    for purpose in ConsentPurpose:
        assert ConsentMapper.describe(purpose).strip()


def test_a_contract_based_purpose_reads_as_granted_but_undecided() -> None:
    """The distinction a UI must not collapse: permitted-by-default is not a yes
    the user gave."""
    state = ConsentMapper.to_state(
        ConsentRecord(user_id="user-1", purpose=ConsentPurpose.ACCOUNT_AND_APPLICATIONS)
    )
    assert state.granted
    assert not state.decided
    assert not state.withdrawable


def _acknowledged_request(
    *,
    acknowledged: bool = True,
    at: datetime = _NOW,
    subject: DataSubjectRef = _SUBJECT,
) -> ErasureRequestInput:
    return ErasureRequestInput(
        subject=subject,
        requested_at=at,
        acknowledged=acknowledged,
        policy_version=_POLICY,
    )


def _consent_input(
    *,
    purpose: str = "answer_reuse",
    granted: bool = True,
    at: datetime = _NOW,
) -> RecordConsentInput:
    return RecordConsentInput(
        user_id="user-1",
        purpose=purpose,
        granted=granted,
        decided_at=at,
        policy_version=_POLICY,
    )
