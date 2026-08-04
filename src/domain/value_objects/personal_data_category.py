"""PersonalDataCategory — one declared kind of personal data this application
is responsible for, and what happens to it when the user exercises a right.

Why a declared inventory rather than code that walks the schema
---------------------------------------------------------------
An export or an erasure built by reflecting over the ORM would look complete
and be wrong in the two ways that matter. It would miss everything held outside
the database — the résumé bytes on disk, the prompts sent to a model provider,
the application a user submitted to an employer's ATS — and it would have no
opinion about the things it *did* find, so a column added next year would be
silently exported or silently deleted according to whichever default the
reflection happened to have.

A declared inventory inverts that. Each category states, in one place, what the
data is, where it lives, why it may be held, whether it goes into a portable
copy, and what an erasure request does to it. A table that is not declared is
not covered, and a test
(`tests/infrastructure/test_personal_data_inventory_covers_schema.py`) turns
that into a build failure: adding a user-scoped table forces a decision here
instead of quietly widening the gap. Same shape as the sensitive-column
convention this codebase already uses — declare it in metadata, then let a test
hold the declaration and the implementation together.

The other thing the inventory buys is honesty about what is *not* automated.
Data held by a model provider or by an employer cannot be deleted by this
codebase, and a compliance story that quietly omits them is the failure mode
this whole exercise exists to avoid. Those categories are declared too, with a
disposition that says who has to act and a note saying how — so the deferred
work is visible in the export the user receives, not only in a document nobody
reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.lawful_basis import LawfulBasis


class PersonalDataStore(StrEnum):
    """Where a category physically lives — which decides who can act on it."""

    #: This application's Postgres database. Readable and erasable here.
    PRIMARY_DATABASE = "primary_database"

    #: The blob store behind `FileStoragePort` (local disk today, object
    #: storage later). Erasable here; the export carries a manifest rather
    #: than the bytes, because a portable copy is a JSON document.
    FILE_STORAGE = "file_storage"

    #: Application logs. Personal data is kept out of these by construction
    #: (ADR 0003), which is why the disposition is not an erasure — there is
    #: nothing there to erase, and a log sink has no per-user delete anyway.
    LOG_SINK = "log_sink"

    #: A third party processing data on this application's instructions — the
    #: model and embedding providers. Erasure is contractual, not a call this
    #: codebase can make.
    PROCESSOR = "processor"

    #: A third party that decides for itself what to do with the data — an
    #: employer's ATS, once the user has applied. Not a processor: ApplyFlow
    #: cannot instruct it, and the user's rights against it are exercised
    #: directly.
    THIRD_PARTY_CONTROLLER = "third_party_controller"

    @property
    def is_locally_held(self) -> bool:
        """Whether this application itself stores the data, and can therefore
        read it for an export and delete it for an erasure."""
        return self in _LOCALLY_HELD


class ErasureDisposition(StrEnum):
    """What an erasure request does to a category. Exactly one per category,
    and the four members cover the four honest answers."""

    #: This application deletes it. The only disposition the erasure path acts
    #: on, and the one every locally-held category of personal data has.
    ERASE = "erase"

    #: Kept, with a stated basis that outranks the erasure right (GDPR Art.
    #: 17(3)). In this codebase that is the consent ledger and nothing else:
    #: Art. 7(1) requires the controller to be able to demonstrate consent,
    #: including the withdrawal that triggered the erasure.
    RETAIN_LEGAL_BASIS = "retain_legal_basis"

    #: Nothing personal is kept here in the first place, so an erasure has
    #: nothing to do. Declared rather than omitted, because "we do not log
    #: personal data" is a claim worth making explicitly and worth having a
    #: test behind (ADR 0003).
    NO_PERSONAL_DATA_RETAINED = "no_personal_data_retained"

    #: Another party has to erase it. The note says who and how. Deferred, and
    #: reported as deferred in the export and the erasure receipt rather than
    #: counted as done.
    DELEGATED = "delegated"


@dataclass(frozen=True)
class PersonalDataCategory:
    """One declared category of personal data, with its rights disposition."""

    #: Stable identifier. Appears in the export document and is what the
    #: `PersonalDataStorePort` adapter keys its handlers on, so renaming one is
    #: a coordinated change, not an edit.
    key: str
    #: What the data is, in words a user reading their export would follow.
    #: This doubles as the notice-at-collection text CCPA/CPRA asks for, which
    #: is why it describes the data rather than the table.
    description: str
    #: Where it lives.
    store: PersonalDataStore
    #: Why it may be held.
    lawful_basis: LawfulBasis
    #: Whether it goes into the portable copy (GDPR Art. 15/20).
    exportable: bool
    #: What erasure does to it.
    erasure: ErasureDisposition
    #: The database tables this category covers — the link between the
    #: inventory and the schema, and what the coverage test compares against
    #: `Base.metadata`. Required for `PRIMARY_DATABASE`, empty for every other
    #: store: naming a table for data that is not in the database would make
    #: the coverage test agree with a false statement.
    tables: tuple[str, ...] = ()
    #: Why this disposition, and — where the answer is "someone else acts" —
    #: what that someone has to do. Required for any disposition other than
    #: `ERASE`, because those are the ones a reader will question.
    note: str = ""

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise InvalidValueError("PersonalDataCategory.key is required.")
        if not self.description.strip():
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' needs a description: it is "
                "what the user reads in their export and what a "
                "notice-at-collection is written from."
            )
        if not isinstance(self.store, PersonalDataStore):
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' needs a valid " "PersonalDataStore."
            )
        if not isinstance(self.lawful_basis, LawfulBasis):
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' needs a valid LawfulBasis."
            )
        if not isinstance(self.erasure, ErasureDisposition):
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' needs a valid "
                "ErasureDisposition."
            )
        self._validate_tables()
        self._validate_exportability()
        self._validate_disposition()

    def _validate_tables(self) -> None:
        in_database = self.store is PersonalDataStore.PRIMARY_DATABASE
        if in_database and not self.tables:
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' is held in the primary "
                "database, so it must name the tables it covers — that list is "
                "what ties the inventory to the schema."
            )
        if not in_database and self.tables:
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' is held in "
                f"'{self.store.value}', not the database, so it must not name "
                "tables; the coverage test would then agree with a false "
                "statement."
            )
        if len(set(self.tables)) != len(self.tables):
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' names a table twice."
            )

    def _validate_exportability(self) -> None:
        if self.exportable and not self.store.is_locally_held:
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' is marked exportable but "
                f"lives in '{self.store.value}', which this application cannot "
                "read from. Describe it as a deferred category instead."
            )

    def _validate_disposition(self) -> None:
        if self.erasure is ErasureDisposition.ERASE:
            if not self.store.is_locally_held:
                raise InvalidValueError(
                    f"PersonalDataCategory '{self.key}' cannot be erased by "
                    f"this application: it lives in '{self.store.value}'. Use "
                    "DELEGATED and say who has to act."
                )
            return
        # Every non-erasure disposition is a reason the user's data is still
        # somewhere after they asked for it to be gone. Each one has to say why.
        if not self.note.strip():
            raise InvalidValueError(
                f"PersonalDataCategory '{self.key}' has disposition "
                f"'{self.erasure.value}' rather than erasure, so it needs a "
                "note saying why and who acts. An unexplained exception to the "
                "erasure right is the thing this field exists to prevent."
            )

    @property
    def is_erased_locally(self) -> bool:
        """Whether the erasure path actually deletes this category."""
        return self.erasure is ErasureDisposition.ERASE

    @property
    def needs_local_handler(self) -> bool:
        """Whether `PersonalDataStorePort` has to implement this category.

        True for anything the application reads for an export or deletes for an
        erasure — which is what the adapter-coverage test asserts against.
        """
        return self.store.is_locally_held and (
            self.exportable or self.is_erased_locally
        )


_LOCALLY_HELD: frozenset[PersonalDataStore] = frozenset(
    {PersonalDataStore.PRIMARY_DATABASE, PersonalDataStore.FILE_STORAGE}
)
