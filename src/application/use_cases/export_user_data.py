"""ExportUserData use case — a complete, portable copy of one person's data.

GDPR Art. 15 (right of access) and Art. 20 (right to data portability), and
CCPA/CPRA §1798.110 (right to know) and §1798.130 (delivery), all want the same
artifact: everything held about the person, in a form they can read and a
machine can parse, with enough context to be checkable.

What this use case actually does — since the reading and the queries belong to
the adapter — is the part that makes the document trustworthy:

1. **Asks for exactly what the inventory declares.** The category list comes
   from `PersonalDataInventory`, not from the adapter. An adapter that grew a
   handler nobody declared cannot smuggle a section in, and an inventory
   category the adapter forgot cannot be quietly dropped.
2. **Refuses to deliver a partial copy.** If the adapter's answer is missing a
   requested category, that raises (`PersonalDataCoverageError`). An export
   short by one section looks exactly like an export of someone who had no data
   in it, which is the one failure mode nobody would notice.
3. **Includes what is not here.** The categories held by a processor or an
   employer, and the log sink that holds nothing, are listed as deferred with
   their notes. The user learns where the rest of their data is from the export
   itself.
4. **Includes the consent ledger.** Both the current state per purpose and the
   full decision history, because "what did I agree to, and when?" is part of
   what an access request asks and the ledger is the only place that answers it.

Sensitive data by definition: this reads every encrypted column there is. The
caller must already be inside an authorized decryption scope, which for the HTTP
path means the request went through `get_current_user`. The use case does not
open one itself — the application layer cannot import the security module, and
more to the point a use case that granted itself decryption would be exactly the
hole `sensitive_access.py` was written to close.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from src.application.dtos.data_rights_dtos import (
    DataSubjectRef,
    DeferredCategoryOutput,
    ExportedCategoryOutput,
    PersonalDataExportOutput,
    PersonalDataRecord,
)
from src.application.exceptions import PersonalDataCoverageError
from src.application.mappers.consent_mapper import ConsentMapper
from src.application.ports.personal_data_store_port import PersonalDataStorePort
from src.domain.entities.consent_record import ConsentRecord
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.services.personal_data_inventory import (
    PERSONAL_DATA_INVENTORY,
    PersonalDataInventory,
)
from src.domain.value_objects.personal_data_category import PersonalDataCategory

#: The shape of the export document. Bump it when a field is added or renamed —
#: a recipient parsing last year's export has to be able to tell.
EXPORT_FORMAT_VERSION = "1.0"


class ExportUserData:
    def __init__(
        self,
        *,
        store: PersonalDataStorePort,
        consent_repository: ConsentRepository,
        inventory: PersonalDataInventory = PERSONAL_DATA_INVENTORY,
    ) -> None:
        self._store = store
        self._consent_repository = consent_repository
        self._inventory = inventory

    async def execute(
        self, subject: DataSubjectRef, *, generated_at: datetime
    ) -> PersonalDataExportOutput:
        exportable = self._inventory.exportable()
        keys = [category.key for category in exportable]
        records = await self._store.read(subject=subject, category_keys=keys)

        missing = tuple(key for key in keys if key not in records)
        if missing:
            raise PersonalDataCoverageError("data export", missing)

        consents = await self._consent_repository.list_for_user(subject.user_id)
        return PersonalDataExportOutput(
            format_version=EXPORT_FORMAT_VERSION,
            subject_user_id=subject.user_id,
            generated_at=generated_at,
            consent_policy_version=_latest_policy_version(consents),
            categories=tuple(
                _to_section(category, records[category.key]) for category in exportable
            ),
            deferred_categories=tuple(
                _to_deferred(category)
                for category in self._inventory.categories
                if not category.exportable
            ),
            consents=tuple(ConsentMapper.to_state(record) for record in consents),
            consent_history=tuple(
                ConsentMapper.to_decision(decision)
                for record in consents
                for decision in record.history
            ),
            limitations=_limitations(subject, self._inventory),
        )


def _to_section(
    category: PersonalDataCategory,
    records: tuple[PersonalDataRecord, ...],
) -> ExportedCategoryOutput:
    return ExportedCategoryOutput(
        key=category.key,
        description=category.description,
        store=category.store.value,
        lawful_basis=category.lawful_basis.value,
        record_count=len(records),
        records=records,
    )


def _to_deferred(category: PersonalDataCategory) -> DeferredCategoryOutput:
    return DeferredCategoryOutput(
        key=category.key,
        description=category.description,
        store=category.store.value,
        lawful_basis=category.lawful_basis.value,
        disposition=category.erasure.value,
        note=category.note,
    )


def _latest_policy_version(records: Sequence[ConsentRecord]) -> str | None:
    """The most recent notice version any decision was made against.

    Reported at the top of the export as the version of the notice the person's
    choices were made under. None when they have never answered anything, which
    is a truthful "no notice has been accepted" rather than a default worth
    inventing.
    """
    decisions = [decision for record in records for decision in record.history]
    if not decisions:
        return None
    return max(decisions, key=lambda decision: decision.decided_at).policy_version


def _limitations(
    subject: DataSubjectRef, inventory: PersonalDataInventory
) -> tuple[str, ...]:
    """Caveats that make this copy less than complete, stated in the document.

    One case today: the `legacy_applications` category is keyed by email address
    rather than account id, so a request whose token carried no email claim
    cannot reach those rows. Reporting an empty section would read as "you had
    none"; saying so lets the person ask again with an address.
    """
    if subject.email:
        return ()
    email_keyed = tuple(
        category.key
        for category in inventory.exportable()
        if category.key == "legacy_applications"
    )
    if not email_keyed:
        return ()
    return (
        "This request carried no email address, so records filed under an "
        f"address rather than an account id ({', '.join(email_keyed)}) could "
        "not be searched. Any such records are not included and are not "
        "reported as absent.",
    )
