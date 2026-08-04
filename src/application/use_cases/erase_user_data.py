"""EraseUserData use case — the right to erasure, honored across every store.

GDPR Art. 17 and CCPA/CPRA §1798.105. The hard part of erasure is not the
DELETE; it is knowing what the full set of places is, and being able to say
afterwards what happened to each one. So this use case is built around the same
declaration the export reads:

1. **Withdraw consent first, then delete.** The withdrawals are appended to the
   consent ledger before anything is erased, and the ledger is the one category
   deliberately retained (Art. 7(1) — the controller must be able to demonstrate
   consent, which includes demonstrating that a withdrawal was honored). Erasing
   without recording the withdrawal would leave an account that merely stopped
   existing, with nothing to show the request was made or acted on.
2. **Erase exactly the categories the inventory dispositions `ERASE`.** Not
   whatever the adapter is willing to delete. A category the inventory retains
   for a legal reason is not deleted here even if the adapter could.
3. **Refuse to report a partial erasure as done.** A category with no answer
   raises (`PersonalDataCoverageError`) rather than being omitted from the
   receipt. Half an erasure is worse than a failed one, because only the failure
   tells anyone to try again.
4. **Report what survived, and why.** `ErasureOutput.retained` carries the
   categories held by a processor, held by an employer, held under a legal
   basis, or holding nothing personal at all — each with the note saying who has
   to act. A receipt listing only deletions would let a reader assume the rest
   was nothing.

Not reversible, and not partially applicable: there is no "erase my answers but
keep my profile" here. Selective deletion of one category is an ordinary product
operation (delete a résumé, discard a review) and belongs with those use cases;
this is the account-level request, and it deletes everything erasable.

Like the export, this reads sensitive columns on the way to deleting them (the
résumé blob keys have to be read before the rows go), so the caller must already
be inside an authorized decryption scope.
"""

from __future__ import annotations

from src.application.dtos.data_rights_dtos import (
    DeferredCategoryOutput,
    ErasedCategoryOutput,
    ErasureOutput,
    ErasureRequestInput,
)
from src.application.exceptions import (
    ErasureNotAcknowledgedError,
    PersonalDataCoverageError,
)
from src.application.ports.personal_data_store_port import PersonalDataStorePort
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.services.personal_data_inventory import (
    PERSONAL_DATA_INVENTORY,
    PersonalDataInventory,
)
from src.domain.value_objects.consent_decision import ConsentDecision
from src.domain.value_objects.consent_purpose import ConsentPurpose


class EraseUserData:
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

    async def execute(self, request: ErasureRequestInput) -> ErasureOutput:
        if not request.acknowledged:
            raise ErasureNotAcknowledgedError

        withdrawn = await self._withdraw_consents(request)

        erasable = self._inventory.erasable()
        keys = [category.key for category in erasable]
        counts = await self._store.erase(subject=request.subject, category_keys=keys)
        missing = tuple(key for key in keys if key not in counts)
        if missing:
            raise PersonalDataCoverageError("data erasure", missing)

        return ErasureOutput(
            subject_user_id=request.subject.user_id,
            executed_at=request.requested_at,
            erased=tuple(
                ErasedCategoryOutput(
                    key=category.key,
                    description=category.description,
                    store=category.store.value,
                    records_erased=counts[category.key],
                )
                for category in erasable
            ),
            retained=tuple(
                DeferredCategoryOutput(
                    key=category.key,
                    description=category.description,
                    store=category.store.value,
                    lawful_basis=category.lawful_basis.value,
                    disposition=category.erasure.value,
                    note=category.note,
                )
                for category in self._inventory.retained_on_erasure()
            ),
            consents_withdrawn=withdrawn,
            limitations=self._limitations(request),
        )

    async def _withdraw_consents(self, request: ErasureRequestInput) -> tuple[str, ...]:
        """Record a withdrawal for every consent actually in effect, before
        deleting.

        Two filters, and both keep the ledger a record of events rather than of
        the erasure's own bookkeeping:

        * **Only withdrawable purposes.** A withdrawal against a contract-based
          purpose is refused by `ConsentDecision` itself, and rightly — this
          erasure *is* how that processing stops, so an entry claiming the user
          switched it off would misdescribe what happened.
        * **Only purposes currently granted.** A purpose the user never granted
          is already denied by default, and one they withdrew last month is
          already withdrawn; appending "withdrawn" to either would record a
          decision nobody made and leave the retained ledger full of entries
          that demonstrate nothing. (`ConsentRecord.record` would catch the
          second case as a restatement, but not the first, where the ledger is
          empty and there is nothing to restate.)

        So the receipt names exactly the consents this request revoked.
        """
        withdrawn: list[str] = []
        for purpose in ConsentPurpose:
            if not purpose.is_withdrawable:
                continue
            record = await self._consent_repository.get(
                user_id=request.subject.user_id, purpose=purpose
            )
            if not record.is_granted:
                continue
            changed = record.record(
                ConsentDecision(
                    purpose=purpose,
                    granted=False,
                    decided_at=request.requested_at,
                    policy_version=request.policy_version,
                )
            )
            if changed:
                await self._consent_repository.save(record)
                withdrawn.append(purpose.value)
        return tuple(withdrawn)

    def _limitations(self, request: ErasureRequestInput) -> tuple[str, ...]:
        """Caveats that keep the receipt from overstating what was erased.

        The `legacy_applications` category is keyed by email address rather than
        account id, so a request whose token carried no email claim cannot reach
        those rows. A receipt reporting zero for that category would read as
        "there were none"; this says the search could not run.
        """
        if request.subject.email:
            return ()
        keys = tuple(
            category.key
            for category in self._inventory.erasable()
            if category.key == "legacy_applications"
        )
        if not keys:
            return ()
        return (
            "This request carried no email address, so records filed under an "
            f"address rather than an account id ({', '.join(keys)}) could not "
            "be searched and were not erased. Repeat the request with an email "
            "address to reach them.",
        )
