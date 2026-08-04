"""A static guard on the personal-data inventory: it has to keep up with the
schema and with the adapter.

Why this is a guard and not a unit test
---------------------------------------
The export and erasure paths are only as complete as the inventory that drives
them, and an inventory falls out of date silently. A table added next year with a
`user_id` column would be stored, queried, and backed up like everything else,
and nothing in a passing test suite would notice that nobody's export contains
it and no erasure deletes it. The failure surfaces years later as a subject
access request that came back short.

So the guard runs in both directions, against the two things the inventory has to
agree with:

* **The schema.** It works out, from `Base.metadata` alone, which tables carry
  data reachable from a person, and fails if that set differs from the tables the
  inventory declares. Reachability is transitive — a table with no `user_id` that
  points at one that has it is still that person's data — which is what catches
  the child tables (`application_status_events` has no user column of its own).
* **The adapter.** `PersonalDataStorePort`'s implementation declares the
  categories it handles, and every category the inventory says needs a handler
  has to be in that set — and nothing else. A declared category with no handler
  fails the export at runtime; a handler for a category nobody declared is dead
  code that will never be called by either path.

Both halves are pure metadata reads: no database, no subject, no data. Same style
and same reasoning as `test_pii_log_call_sites.py`, which ties the log-guard's
banned names to the sensitive-column flags — a declaration is only worth having
if something fails when it drifts.

And, following the lesson that a guard which silently stops matching looks
exactly like a clean codebase: there are meta-tests below asserting that the
reachability walk actually sees the tables it should, and that it would catch a
planted violation.
"""

from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table

from src.application.ports.file_storage_port import FileStoragePort
from src.domain.services.personal_data_inventory import PERSONAL_DATA_INVENTORY
from src.infrastructure.persistence.models import Base
from src.infrastructure.persistence.personal_data_store_impl import (
    SqlAlchemyPersonalDataStore,
)

#: Tables that hold no personal data at all, and why. Listed explicitly rather
#: than inferred, so a table that stops being impersonal has to be moved out of
#: here by hand:
#:
#: - `job_postings` — an employer's public listing. Nothing about a candidate.
#: - `resolved_company_boards` — which ATS a company's jobs are hosted on. A
#:   permanent cache keyed by company name.
#:
#: Neither is reachable from a user, so the walk below already excludes them;
#: naming them here is what makes the *count* meaningful — an empty exclusion
#: list with a broken walk would look the same as a covered schema.
_IMPERSONAL_TABLES: frozenset[str] = frozenset(
    {"job_postings", "resolved_company_boards"}
)

#: Columns that identify a person directly. `profile_id` is here because the
#: profile aggregate's children key on it rather than on the user, and
#: `candidate_email_bidx` because `job_applications` predates the account model
#: and files rows under an address.
_SUBJECT_COLUMNS: frozenset[str] = frozenset(
    {"user_id", "profile_id", "candidate_email_bidx"}
)


def _personal_tables(metadata: MetaData) -> set[str]:
    """Every table holding data reachable from one person.

    A table qualifies if it has a subject column, if it has a column flagged
    `sensitive` (encryption-at-rest already decided that one holds personal
    data — a table with such a column but no visible owner is worse, not
    better), or if it has a foreign key into a table that qualifies. The last
    clause is iterated to a fixed point, because reachability can be several
    hops deep: `application_status_events` -> `tracked_applications` -> a user.
    """
    personal = {
        name
        for name, table in metadata.tables.items()
        if any(column.name in _SUBJECT_COLUMNS for column in table.columns)
        or any(column.info.get("sensitive") for column in table.columns)
    }
    while True:
        grown = set(personal)
        for name, table in metadata.tables.items():
            if name in grown:
                continue
            for key in table.foreign_keys:
                if key.column.table.name in personal:
                    grown.add(name)
                    break
        if grown == personal:
            return personal
        personal = grown


def test_every_personal_data_table_is_declared_in_the_inventory() -> None:
    """The direction that matters most: a new user-scoped table forces an entry.

    If this fails, the fix is never to add the table to `_IMPERSONAL_TABLES`
    unless it genuinely holds nothing about a person. It is to declare a category
    for it in `src/domain/services/personal_data_inventory.py` and implement its
    handler — otherwise the data is stored but neither exportable nor erasable.
    """
    reachable = _personal_tables(Base.metadata)
    declared = set(PERSONAL_DATA_INVENTORY.covered_tables())

    undeclared = reachable - declared
    assert not undeclared, (
        "These tables hold data reachable from a user but no personal-data "
        "category declares them, so nothing exports or erases their rows. "
        "Declare each one in src/domain/services/personal_data_inventory.py: "
        f"{sorted(undeclared)}"
    )


def test_the_inventory_declares_no_table_that_does_not_exist() -> None:
    """The other direction. A category naming a dropped or renamed table would
    make the inventory look more complete than it is, and the adapter's query for
    it would fail at request time rather than here."""
    declared = set(PERSONAL_DATA_INVENTORY.covered_tables())
    phantom = declared - set(Base.metadata.tables)
    assert not phantom, (
        "The personal-data inventory declares tables that are not in the "
        f"schema: {sorted(phantom)}"
    )


def test_the_inventory_claims_no_impersonal_table() -> None:
    """Erasing a job posting because a candidate asked to be forgotten would
    delete an employer's listing (and, via RESTRICT, fail). Exporting one would
    pad someone's data with someone else's."""
    overreach = set(PERSONAL_DATA_INVENTORY.covered_tables()) & _IMPERSONAL_TABLES
    assert not overreach, (
        "These tables hold no personal data but the inventory claims them: "
        f"{sorted(overreach)}"
    )


def test_the_adapter_handles_every_category_that_needs_a_handler() -> None:
    """A declared category with no handler is a section silently missing from
    every export — which is why `ExportUserData` raises rather than omitting it,
    and why this check exists to catch it before a request does."""
    store = SqlAlchemyPersonalDataStore(_NullSession(), _NullFileStorage())
    handled = store.handled_categories()
    needed = {c.key for c in PERSONAL_DATA_INVENTORY.needing_local_handler()}

    unhandled = needed - handled
    assert not unhandled, (
        "These personal-data categories are declared but the store adapter has "
        "no handler for them, so an export or erasure would refuse: "
        f"{sorted(unhandled)}"
    )


def test_the_adapter_handles_nothing_the_inventory_does_not_declare() -> None:
    """A handler nobody declared is never called by either path — dead code that
    reads as coverage."""
    store = SqlAlchemyPersonalDataStore(_NullSession(), _NullFileStorage())
    declared = {c.key for c in PERSONAL_DATA_INVENTORY.categories}
    stray = store.handled_categories() - declared
    assert not stray, (
        "The store adapter handles categories the inventory does not declare, "
        f"so nothing will ever ask for them: {sorted(stray)}"
    )


def test_the_consent_ledger_has_a_reader_but_no_eraser() -> None:
    """The retained category, from the adapter's side. The user can read their own
    ledger; nothing in this codebase can delete it, which is what makes retaining
    it a property of the code rather than of the caller's argument list."""
    store = SqlAlchemyPersonalDataStore(_NullSession(), _NullFileStorage())
    assert "consents" in store.handled_categories()

    from src.infrastructure.persistence.personal_data_store_impl import (
        _ERASURES,
        _READERS,
    )

    assert "consents" in _READERS
    assert "consents" not in _ERASURES


def test_tracked_applications_are_erased_before_the_documents_they_reference() -> None:
    """A `RESTRICT` foreign key, not a preference: deleting the documents first
    fails the transaction. The order lives in the adapter's mapping, so it is
    asserted there rather than discovered by a smoke test against a real
    database."""
    from src.infrastructure.persistence.personal_data_store_impl import _ERASURES

    order = list(_ERASURES)
    assert order.index("tracked_applications") < order.index("application_documents")


# -- Meta-tests: does the walk actually see anything? ------------------------
#
# A reachability walk that quietly matched nothing would make every assertion
# above pass vacuously, and a clean codebase and a broken guard would be
# indistinguishable.


def test_the_walk_finds_the_tables_it_is_supposed_to_find() -> None:
    reachable = _personal_tables(Base.metadata)
    # Directly keyed on the subject.
    assert "user_profiles" in reachable
    assert "resumes" in reachable
    # Keyed on the profile, not the user.
    assert "eeo_self_identifications" in reachable
    # Two hops: status events -> tracked applications -> user.
    assert "application_status_events" in reachable
    # Keyed by email blind index, with no user column at all.
    assert "job_applications" in reachable
    # And it excludes what it should.
    assert not reachable & _IMPERSONAL_TABLES


def test_the_walk_would_catch_a_new_undeclared_user_scoped_table() -> None:
    """Plants the violation this guard exists to catch, in a throwaway metadata
    object, and asserts the walk reports it."""
    metadata = MetaData()
    Table("bright_ideas", metadata, Column("user_id", String(64), primary_key=True))
    assert _personal_tables(metadata) == {"bright_ideas"}


class _NullSession:
    """Stands in for an `AsyncSession` that is never used.

    `handled_categories()` is a declaration, so it needs no database — and that
    is the property worth preserving: this guard runs on every commit rather than
    only where Postgres is reachable.
    """


class _NullFileStorage(FileStoragePort):
    async def save(self, storage_key: str, content: bytes) -> None:  # pragma: no cover
        raise AssertionError("the coverage guard must not touch storage")

    async def delete(self, storage_key: str) -> None:  # pragma: no cover
        raise AssertionError("the coverage guard must not touch storage")
