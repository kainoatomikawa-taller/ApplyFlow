"""ConsentRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation lives in
infrastructure/. The domain and application layers depend only on this
abstraction, never on a specific database.

Note what is absent: no `update`, and no `delete_decision`. The ledger is
append-only (see `ConsentRecord`), so the only write is `save`, and it appends
whatever entries the record has gained. A repository that could rewrite a
decision would make the ledger unable to serve as the demonstration record
GDPR Art. 7(1) asks for, so the capability is not offered rather than merely
unused.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.consent_record import ConsentRecord
from src.domain.value_objects.consent_purpose import ConsentPurpose


class ConsentRepository(ABC):
    """Persistence contract for consent ledgers."""

    @abstractmethod
    async def get(self, *, user_id: str, purpose: ConsentPurpose) -> ConsentRecord:
        """Return this user's ledger for `purpose`.

        Always returns a record, never None: a user who has never been asked
        has an empty ledger, and that is a state with a definite answer (see
        `ConsentRecord.is_granted`). Returning None would push the opt-in
        default out to every caller.
        """

    @abstractmethod
    async def list_for_user(self, user_id: str) -> list[ConsentRecord]:
        """Return one ledger per declared purpose, including the purposes this
        user has never answered.

        Complete rather than only-what-was-stored, for the same reason `get`
        never returns None: the consent screen and the data export both have to
        show every purpose, and a caller reconstructing the missing ones would
        be reimplementing the default.
        """

    @abstractmethod
    async def save(self, record: ConsentRecord) -> None:
        """Append this record's decisions that are not yet stored.

        Idempotent by construction: the ledger is append-only, so re-saving a
        record that gained nothing writes nothing.
        """
