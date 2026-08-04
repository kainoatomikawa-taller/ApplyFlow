"""Tests for the personal-data inventory.

The inventory is a declaration, so most of what is worth testing is that it
cannot be declared wrongly. Each rule here corresponds to a way an export or an
erasure could be silently incomplete while every other test in the suite still
passed — which is why they are validated at construction rather than checked by
whoever reads it.
"""

from __future__ import annotations

import pytest

from src.domain.exceptions import (
    InvalidValueError,
    UnknownPersonalDataCategoryError,
)
from src.domain.services.personal_data_inventory import (
    PERSONAL_DATA_INVENTORY,
    PersonalDataInventory,
)
from src.domain.value_objects.lawful_basis import LawfulBasis
from src.domain.value_objects.personal_data_category import (
    ErasureDisposition,
    PersonalDataCategory,
    PersonalDataStore,
)


def _category(**overrides: object) -> PersonalDataCategory:
    defaults: dict[str, object] = {
        "key": "widgets",
        "description": "Some widgets.",
        "store": PersonalDataStore.PRIMARY_DATABASE,
        "lawful_basis": LawfulBasis.CONTRACT,
        "exportable": True,
        "erasure": ErasureDisposition.ERASE,
        "tables": ("widgets",),
    }
    defaults.update(overrides)
    return PersonalDataCategory(**defaults)  # type: ignore[arg-type]


# -- Category invariants -----------------------------------------------------


def test_a_database_category_must_name_its_tables() -> None:
    """That list is the only thing tying the inventory to the schema; without it
    the coverage test has nothing to compare."""
    with pytest.raises(InvalidValueError):
        _category(tables=())


def test_a_non_database_category_must_not_name_tables() -> None:
    """Otherwise the coverage test would agree with a false statement — a table
    claimed by a category whose data is not in the database."""
    with pytest.raises(InvalidValueError):
        _category(
            store=PersonalDataStore.PROCESSOR,
            erasure=ErasureDisposition.DELEGATED,
            exportable=False,
            note="The provider deletes it.",
            tables=("widgets",),
        )


def test_a_category_this_application_cannot_read_is_not_exportable() -> None:
    with pytest.raises(InvalidValueError):
        _category(
            store=PersonalDataStore.PROCESSOR,
            erasure=ErasureDisposition.DELEGATED,
            note="The provider deletes it.",
            exportable=True,
            tables=(),
        )


def test_a_category_this_application_cannot_reach_cannot_be_dispositioned_erase() -> (
    None
):
    """`ERASE` is a claim that this codebase deletes the data. Claiming it for a
    third party's store is how a receipt ends up reporting an erasure that never
    happened."""
    with pytest.raises(InvalidValueError):
        _category(
            store=PersonalDataStore.THIRD_PARTY_CONTROLLER,
            exportable=False,
            erasure=ErasureDisposition.ERASE,
            tables=(),
        )


def test_any_disposition_other_than_erase_needs_a_note() -> None:
    """Every non-erasure disposition is a reason the user's data is still
    somewhere after they asked for it to be gone. An unexplained exception to the
    erasure right is exactly what this field exists to prevent."""
    with pytest.raises(InvalidValueError) as excinfo:
        _category(erasure=ErasureDisposition.RETAIN_LEGAL_BASIS, note="")
    assert "note" in str(excinfo.value)


def test_needs_local_handler_covers_what_the_adapter_must_implement() -> None:
    assert _category().needs_local_handler
    # Retained but exportable still needs a reader.
    assert _category(
        erasure=ErasureDisposition.RETAIN_LEGAL_BASIS, note="Kept as proof."
    ).needs_local_handler
    # Neither read nor deleted here: nothing for the adapter to do.
    assert not _category(
        store=PersonalDataStore.LOG_SINK,
        exportable=False,
        erasure=ErasureDisposition.NO_PERSONAL_DATA_RETAINED,
        note="Nothing personal is written here.",
        tables=(),
    ).needs_local_handler


# -- Inventory invariants ----------------------------------------------------


def test_duplicate_category_keys_are_refused() -> None:
    with pytest.raises(InvalidValueError):
        PersonalDataInventory((_category(), _category()))


def test_a_table_claimed_by_two_categories_is_refused() -> None:
    """The one arrangement that passes a coverage check while behaving wrongly:
    an erasure would run twice against the table and an export would list its
    rows twice, and neither is visible from the declaration."""
    with pytest.raises(InvalidValueError) as excinfo:
        PersonalDataInventory(
            (_category(), _category(key="gadgets", tables=("widgets",)))
        )
    assert "widgets" in str(excinfo.value)


def test_an_inventory_with_nothing_erasable_is_refused() -> None:
    with pytest.raises(InvalidValueError):
        PersonalDataInventory(
            (
                _category(
                    erasure=ErasureDisposition.RETAIN_LEGAL_BASIS,
                    note="Kept as proof.",
                ),
            )
        )


def test_an_empty_inventory_is_refused() -> None:
    with pytest.raises(InvalidValueError):
        PersonalDataInventory(())


def test_asking_for_an_undeclared_category_raises_rather_than_returning_none() -> None:
    """A caller on an export or erasure path that shrugged off a missing category
    would produce an incomplete answer to a legal request."""
    with pytest.raises(UnknownPersonalDataCategoryError):
        PERSONAL_DATA_INVENTORY.category("not_a_category")


# -- The real inventory ------------------------------------------------------


def test_the_declared_inventory_covers_the_stores_that_actually_exist() -> None:
    """Every place this application puts personal data has a category. The point
    is the two that are easy to forget: the blob store holding résumé files, and
    the third parties the data is disclosed to."""
    stores = {category.store for category in PERSONAL_DATA_INVENTORY.categories}
    assert stores == set(PersonalDataStore)


def test_every_disposition_is_used_and_each_non_erasure_one_explains_itself() -> None:
    """A disposition nobody uses is a distinction nobody has thought about; a
    used one with no note is an unexplained hole in the erasure right."""
    dispositions = {category.erasure for category in PERSONAL_DATA_INVENTORY.categories}
    assert dispositions == set(ErasureDisposition)
    for category in PERSONAL_DATA_INVENTORY.retained_on_erasure():
        assert category.note.strip(), category.key


def test_the_consent_ledger_is_retained_and_says_why() -> None:
    """The one deliberate exception to "erasure deletes everything", and the one
    most likely to be read as a bug. GDPR Art. 7(1) needs the record that the
    withdrawal was honored; deleting it would destroy the evidence that the
    erasure itself was lawful."""
    consents = PERSONAL_DATA_INVENTORY.category("consents")
    assert consents.erasure is ErasureDisposition.RETAIN_LEGAL_BASIS
    assert consents.lawful_basis is LawfulBasis.LEGAL_OBLIGATION
    assert consents.exportable, "the user must still be able to read their own"
    assert "7(1)" in consents.note


def test_the_special_category_tables_are_inside_the_profile_category() -> None:
    """Work authorization and EEO self-identification are the data most
    consequential to leave behind, so their tables have to be accounted for
    rather than assumed to travel with the profile row."""
    profile = PERSONAL_DATA_INVENTORY.category("profile")
    assert "work_authorizations" in profile.tables
    assert "eeo_self_identifications" in profile.tables


def test_erasable_and_exportable_are_not_the_same_set() -> None:
    """If they were, one of the two lists would be redundant and the inventory
    would have stopped distinguishing "you can see this" from "we will delete
    this" — which are genuinely different questions (the consent ledger is the
    case in point)."""
    exportable = {c.key for c in PERSONAL_DATA_INVENTORY.exportable()}
    erasable = {c.key for c in PERSONAL_DATA_INVENTORY.erasable()}
    assert exportable != erasable
    assert "consents" in exportable - erasable
