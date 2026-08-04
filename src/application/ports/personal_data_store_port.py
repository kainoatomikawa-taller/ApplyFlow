"""PersonalDataStorePort — an outbound port for reading and erasing everything
this application holds about one person.

Why a port and not a fan of repositories
----------------------------------------
The obvious shape for an export use case is "inject all eleven repositories and
call `list_by_user_id` on each". It does not survive contact with the actual
requirements:

* **Erasure order is a database fact.** `tracked_applications` references
  `application_documents` with `ON DELETE RESTRICT`, so the tracker rows have to
  go first or the delete fails. A use case that knew that would be encoding the
  schema's foreign keys — exactly the knowledge the dependency rule keeps out of
  the application layer.
* **A portable copy is not a set of domain entities.** Art. 20 asks for the data
  in a "structured, commonly used, machine-readable format", which means every
  stored column including the ones no entity exposes. Rebuilding that from
  entities would export what the domain models rather than what is stored, and
  the difference between those two is the part a regulator asks about.
* **Not everything is behind a repository.** Résumé bytes live in blob storage;
  a complete erasure has to reach them too.

So the application layer asks for what it actually needs — read these
categories, erase these categories — and lets infrastructure decide the queries,
the join order and the delete order. What stays here is the part that is not
about storage: checking the answer against the inventory, assembling the export
envelope, and reporting what was deferred (see `ExportUserData` and
`EraseUserData`).

Categories, not tables. The keys are the ones declared in
`PersonalDataInventory`; the adapter maps each to whatever queries it takes. A
test asserts the two sides agree, so a category with no handler is a build
failure rather than a silently missing section of somebody's export.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence

from src.application.dtos.data_rights_dtos import (
    DataSubjectRef,
    PersonalDataRecord,
)


class PersonalDataStorePort(ABC):
    """Reads and erases one person's data across the stores this application
    owns."""

    @abstractmethod
    def handled_categories(self) -> frozenset[str]:
        """The inventory category keys this adapter can act on.

        Declared rather than discovered so the coverage test can compare it
        against `PersonalDataInventory.needing_local_handler()` without a
        database, a subject, or any data — which is what makes the check run on
        every commit instead of only where Postgres is reachable.
        """

    @abstractmethod
    async def read(
        self, *, subject: DataSubjectRef, category_keys: Sequence[str]
    ) -> Mapping[str, tuple[PersonalDataRecord, ...]]:
        """Return every stored record for `subject` in each requested category.

        The result must have a key for every requested category, with an empty
        tuple where the person has no data — the caller distinguishes "nothing
        stored" from "not collected", and only an explicit empty tuple lets it.

        Reads sensitive columns, so callers must already be inside an authorized
        decryption scope (see
        `src/infrastructure/security/sensitive_access.py`). An export is the
        clearest legitimate case there is for decrypting a person's whole
        record, and it is still required to say so.
        """

    @abstractmethod
    async def erase(
        self, *, subject: DataSubjectRef, category_keys: Sequence[str]
    ) -> Mapping[str, int]:
        """Delete `subject`'s data in each requested category; return the count
        of records removed per category.

        Must have a key for every requested category, zero included: the
        erasure receipt reports per-category counts, and a missing key would
        read as "not attempted" where the truth is "nothing was there".

        Implementations own the ordering. The tracker's foreign keys are
        `RESTRICT`, so some categories have to be deleted before others, and
        which ones is a property of the schema rather than of the request.

        Expected to be atomic per call: a half-erased account is worse than a
        failed erasure, because nothing tells the next reader which half.
        """
