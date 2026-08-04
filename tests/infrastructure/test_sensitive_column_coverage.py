"""The lockstep guard: every sensitive column is actually encrypted, and every
free-text column on a personal-data table has been ruled on either way.

`models.py` and `encrypted_types.py` both name this file as the mechanism that
keeps the `sensitive` flag and the encrypted column type from drifting apart —
"adding a column here and flagging it is enough to be told that it also needs
encrypting". Until the Epic 07 hardening pass, it did not exist. That is the
worst failure mode available to a control like this: the codebase asserted a
safety net in two docstrings, reviewers reasonably believed it, and nothing
checked.

Four groups of checks, and the fourth is the one that earns its keep.

1. **Flag ⇔ encryption.** A flagged column must use an encrypted type, and an
   encrypted column must be flagged. Both directions, because a column encrypted
   but unflagged is invisible to every other tool that reads the flag — the log
   guard's banned-name sync, the personal-data inventory, this file.
2. **Purpose strings.** Each encrypted column's `purpose` must be exactly
   `table.column`. The purpose is authenticated into the ciphertext as GCM
   additional data, so a typo does not fail loudly at deploy time — it writes
   rows that decrypt nowhere, and only for the columns nobody exercised.
3. **Storage shape.** Ciphertext columns are `Text`, carry no server default,
   and are not indexed. Each of those has bitten this codebase or was one edit
   away from doing so (migrations 0021 and 0023 both had to drop a
   `server_default` that would otherwise insert plaintext).
4. **Nothing free-text is left undecided.** Every `Text`/`JSON`/long-`String`
   column on a table the personal-data inventory covers must be either encrypted
   or listed in `_REVIEWED_PLAINTEXT` with a reason. This is the check that
   catches the class of gap the hardening pass found by hand: not "flagged but
   not encrypted" (checks 1-3 cover that) but *"should have been flagged and
   nobody noticed"* — `job_applications.tailored_cover_letter`, a whole cover
   letter sitting in the clear beside an encrypted column holding the same thing.

All of it reads `Base.metadata`. No database, no keys, no fixtures — so this
runs on every commit rather than only where Postgres is reachable.
"""

from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.sql.schema import Column

from src.domain.services.personal_data_inventory import PERSONAL_DATA_INVENTORY
from src.infrastructure.persistence.encrypted_types import (
    EncryptedBoolean,
    EncryptedJson,
    EncryptedString,
    _EncryptedColumn,
)
from src.infrastructure.persistence.models import Base

_ENCRYPTED_TYPES = (EncryptedString, EncryptedBoolean, EncryptedJson)

#: A column is "free text" — capable of holding a sentence a person wrote — if it
#: is `Text`, `JSON`, or a `String` long enough to be prose rather than an
#: identifier or an enum value. 255 is the threshold because every enum, status,
#: provenance tag and key id in this schema is 64 or shorter, and every name,
#: address line and title is 255.
_FREE_TEXT_MIN_STRING_LENGTH = 255

#: Columns on personal-data tables that hold free text and are deliberately
#: stored in the clear, each with the reason. Anything free-text that is neither
#: encrypted nor in here fails `test_every_free_text_column_has_been_ruled_on`.
#:
#: This list is the audit trail. It is meant to be read as "we looked at each of
#: these and decided", and a reviewer who disagrees with one has a specific claim
#: to argue with rather than an absence to notice.
_REVIEWED_PLAINTEXT: dict[str, str] = {
    # -- The employer's own data. Not personal data about the candidate at all.
    "job_applications.company_name": "The employer's name.",
    "job_applications.role_title": "The role applied for.",
    "job_applications.job_description": "The employer's public posting text.",
    "tracked_applications.company_name": "The employer's name, snapshotted.",
    "tracked_applications.role_title": "The role applied for, snapshotted.",
    "tracked_applications.job_location": "The posting's location, snapshotted.",
    "application_reviews.apply_url": "The employer's public apply URL.",
    "portal_handoffs.apply_url": "The employer's public apply URL.",
    "portal_handoffs.paused_url": (
        "Where automation stopped on the employer's portal. A URL rather than "
        "candidate data; its query string is stripped from every log line by "
        "the PII scrubber (ADR 0003)."
    ),
    "portal_handoffs.hard_stops": (
        "Evidence lines describing the portal's own page — a CAPTCHA widget, a "
        "login wall. Says nothing about the candidate; see PortalHandoffModel, "
        "which contrasts it with the resolution note beside it."
    ),
    # -- Derived metadata that describes personal data without containing it.
    "application_documents.backing_sources": (
        "A JSON array of ProvenanceSource enum values ('parsed_resume', "
        "'user_entered', 'answer'). Says where a document's facts came from, "
        "not what they were."
    ),
    # -- The candidate's CV facts. In the clear, and the largest accepted
    # residual risk in the schema. Epic 07 drew its boundary at contact details,
    # legal declarations, free-text answers and whole documents; the structured
    # CV history was explicitly left out (see UserProfileModel on `headline`).
    #
    # Recorded here as a decision rather than an omission because the same facts
    # ARE encrypted one table over, in `resumes.extracted_text`. That
    # inconsistency is real and is tracked as R1 in
    # docs/epic-07-hardening-check.md, with the argument for closing it.
    "work_history_entries.company_name": "CV fact — see the note above.",
    "work_history_entries.job_title": "CV fact — see the note above.",
    "work_history_entries.location": "CV fact — see the note above.",
    "work_history_entries.description": "CV fact — see the note above.",
    "education_entries.institution_name": "CV fact — see the note above.",
    "education_entries.degree": "CV fact — see the note above.",
    # Replaced `field_of_study` in migration 0025. Same category and the same
    # decision — a JSON array of subject names is no more or less sensitive than
    # the single string it supersedes.
    "education_entries.majors": "CV fact — see the note above.",
    "education_entries.minors": "CV fact — see the note above.",
    "education_entries.description": "CV fact — see the note above.",
    "skills.name": "CV fact — see the note above.",
    "user_profiles.headline": (
        "A self-written professional tagline, same category as the CV facts "
        "above. See UserProfileModel, which states this decision."
    ),
    # Search preferences, not facts about the candidate. "I want summer 2027
    # internships" describes what someone is looking for; it identifies nobody,
    # says nothing about their history, and is the kind of thing a job board shows
    # in its own UI. Encrypting it would also make it unqueryable for no gain,
    # since these are the columns a future "which terms are people searching for"
    # question would read. Free-text-shaped only because they are JSON arrays —
    # the contents are enum values and four-digit years, not prose.
    "user_profiles.desired_employment_types": (
        "A stated preference, not personal data — see the note above."
    ),
    "user_profiles.desired_terms": (
        "A stated preference, not personal data — see the note above."
    ),
    "user_profiles.desired_functions": (
        "A stated preference, not personal data — see the note above."
    ),
    "user_profiles.portfolio_url": "A profile the candidate publishes publicly.",
    "user_profiles.linkedin_url": "A profile the candidate publishes publicly.",
    "user_profiles.github_url": "A profile the candidate publishes publicly.",
}


def _all_columns() -> list[tuple[str, Column[object]]]:
    return [
        (f"{table.name}.{column.name}", column)
        for table in Base.metadata.tables.values()
        for column in table.columns
    ]


def _flagged() -> set[str]:
    return {name for name, column in _all_columns() if column.info.get("sensitive")}


def _encrypted() -> set[str]:
    return {
        name
        for name, column in _all_columns()
        if isinstance(column.type, _ENCRYPTED_TYPES)
    }


# -- 1. Flag <-> encryption ---------------------------------------------------


def test_the_schema_flags_some_columns_sensitive() -> None:
    """Guards against the guard passing vacuously. If the flags ever stop being
    readable — a renamed `info` key, a refactor that drops them — every other
    assertion in this file would silently compare two empty sets."""
    assert len(_flagged()) >= 25, (
        "Expected models.py to flag its sensitive columns; found "
        f"{len(_flagged())}. Has the `info={{'sensitive': True}}` tag moved?"
    )


def test_every_sensitive_flagged_column_is_encrypted() -> None:
    """The claim `models.py` makes about this file, in one assertion."""
    unencrypted = _flagged() - _encrypted()
    assert not unencrypted, (
        "These columns are flagged `sensitive` but are stored in the clear. "
        "Give each an encrypted column type from encrypted_types.py and write "
        "a migration converting existing rows (see 0021 and 0023 for the "
        f"pattern): {sorted(unencrypted)}"
    )


def test_every_encrypted_column_is_flagged_sensitive() -> None:
    """The other direction, and not redundant: the flag is what the log guard's
    banned-name sync, the personal-data inventory, and this file all read. An
    encrypted-but-unflagged column is protected at rest and invisible to every
    other control."""
    unflagged = _encrypted() - _flagged()
    assert not unflagged, (
        "These columns are encrypted but not flagged `sensitive`, so the other "
        "controls that read the flag cannot see them. Add "
        f"`info=_SENSITIVE_COLUMN_INFO`: {sorted(unflagged)}"
    )


# -- 2. Purpose strings -------------------------------------------------------


def test_every_encrypted_column_binds_its_own_table_and_column_name() -> None:
    """`purpose` is authenticated into the ciphertext, so a mismatch is not a
    loud failure — it is rows that decrypt nowhere, discovered whenever someone
    finally reads that column. Checked mechanically because a human reading a
    diff cannot see that `EncryptedString("user_profiles.postal_code")` sits on
    a column named `zip_code`."""
    wrong: list[str] = []
    for name, column in _all_columns():
        if not isinstance(column.type, _ENCRYPTED_TYPES):
            continue
        purpose = column.type.purpose
        if purpose != name:
            wrong.append(f"{name} binds purpose '{purpose}'")
    assert not wrong, (
        "An encrypted column's purpose must be exactly 'table.column' — it is "
        "authenticated into the ciphertext, so a mismatch writes unreadable "
        f"rows: {sorted(wrong)}"
    )


def test_no_two_columns_share_a_purpose() -> None:
    """Two columns with one purpose would make their ciphertext interchangeable,
    which is precisely what the purpose binding exists to prevent — a value
    could be moved between them and still decrypt cleanly."""
    purposes: dict[str, str] = {}
    collisions: list[str] = []
    for name, column in _all_columns():
        if not isinstance(column.type, _ENCRYPTED_TYPES):
            continue
        purpose = column.type.purpose
        if purpose in purposes:
            collisions.append(f"{purposes[purpose]} and {name} share '{purpose}'")
        purposes[purpose] = name
    assert not collisions, collisions


# -- 3. Storage shape ---------------------------------------------------------


def test_encrypted_columns_are_stored_as_text() -> None:
    """Ciphertext has no length and no shape. Asserted against the *database*
    type rather than the Python one, which is what `_EncryptedColumn` exists to
    keep separate."""
    wrong = [
        name
        for name, column in _all_columns()
        if isinstance(column.type, _ENCRYPTED_TYPES)
        and not isinstance(column.type.impl_instance, Text)
    ]
    assert not wrong, wrong


def test_no_encrypted_column_has_a_server_default() -> None:
    """A server-side default on an encrypted column inserts plaintext that
    nothing can decrypt. Both migration 0021 and migration 0023 had to drop one,
    which is exactly why this is a test and not a note."""
    offenders = [
        name
        for name, column in _all_columns()
        if isinstance(column.type, _ENCRYPTED_TYPES)
        and column.server_default is not None
    ]
    assert not offenders, (
        "These encrypted columns have a database-side default, which would "
        "store plaintext no reader can decrypt. Move the default to the Python "
        f"side (`default=`) and drop it in a migration: {offenders}"
    )


def test_no_encrypted_column_is_indexed_or_unique() -> None:
    """An index on randomized ciphertext can serve no query — the same value
    encrypts differently every time — so one is either dead weight or, worse,
    evidence that someone believes the column is searchable. The blind-index
    column beside `job_applications.candidate_email` is the supported way to
    look one up, and it is a separate, unencrypted column by design."""
    offenders: list[str] = []
    for table in Base.metadata.tables.values():
        encrypted = {
            column.name
            for column in table.columns
            if isinstance(column.type, _ENCRYPTED_TYPES)
        }
        for column in table.columns:
            if column.name in encrypted and (column.index or column.unique):
                offenders.append(f"{table.name}.{column.name} (column-level)")
        for index in table.indexes:
            for column in index.columns:
                if column.name in encrypted:
                    offenders.append(f"{table.name}.{column.name} (in {index.name})")
        for constraint in table.constraints:
            for column in getattr(constraint, "columns", []):
                if column.name in encrypted:
                    offenders.append(
                        f"{table.name}.{column.name} (in {constraint.name})"
                    )
    assert not offenders, (
        "Encrypted columns cannot be indexed or constrained by value — "
        "ciphertext is randomized, so nothing matches. Use a blind-index "
        f"column instead (see FieldCipher.blind_index): {sorted(offenders)}"
    )


# -- 4. Nothing free-text left undecided --------------------------------------


def _free_text_columns_on_personal_tables() -> set[str]:
    """Columns that could hold a sentence a person wrote, on tables the
    personal-data inventory says belong to a person."""
    personal = PERSONAL_DATA_INVENTORY.covered_tables()
    found: set[str] = set()
    for table in Base.metadata.tables.values():
        if table.name not in personal:
            continue
        for column in table.columns:
            if isinstance(column.type, _ENCRYPTED_TYPES):
                continue
            type_ = column.type
            is_free_text = isinstance(type_, Text | JSON) or (
                isinstance(type_, String)
                and (type_.length or 0) >= _FREE_TEXT_MIN_STRING_LENGTH
            )
            if is_free_text:
                found.add(f"{table.name}.{column.name}")
    return found


def test_every_free_text_column_has_been_ruled_on() -> None:
    """The check that catches "should have been flagged and nobody noticed".

    Checks 1-3 above verify that a column someone remembered to flag is
    encrypted. They cannot catch the gap the hardening pass actually found,
    which was a column nobody flagged: a full cover letter in
    `job_applications.tailored_cover_letter`, in the clear, next to an encrypted
    column holding the same class of document.

    So: a free-text column on a personal-data table is either encrypted or
    explicitly recorded as reviewed. Adding one forces a decision, and the
    decision is written down where the next reviewer can disagree with it.
    """
    undecided = _free_text_columns_on_personal_tables() - set(_REVIEWED_PLAINTEXT)
    assert not undecided, (
        "These columns can hold free text on a table holding personal data, "
        "and are neither encrypted nor recorded as reviewed. Encrypt each one "
        "(flag it, give it an encrypted type, write a migration) or add it to "
        "_REVIEWED_PLAINTEXT in this file with the reason it is safe in the "
        f"clear: {sorted(undecided)}"
    )


def test_the_reviewed_plaintext_list_has_no_stale_entries() -> None:
    """An entry for a column that is now encrypted, renamed, or dropped is a
    claim nobody is checking any more — and it would mask a *new* column
    arriving under the old name."""
    stale = set(_REVIEWED_PLAINTEXT) - _free_text_columns_on_personal_tables()
    assert not stale, (
        "These entries in _REVIEWED_PLAINTEXT no longer describe a plaintext "
        f"free-text column on a personal-data table; remove them: {sorted(stale)}"
    )


def test_every_reviewed_plaintext_entry_gives_a_reason() -> None:
    for name, reason in _REVIEWED_PLAINTEXT.items():
        assert len(reason.strip()) >= 20, (
            f"_REVIEWED_PLAINTEXT['{name}'] needs a real reason; an unexplained "
            "exception is what this list exists to prevent."
        )


# -- Meta: does the walk actually see anything? -------------------------------


def test_the_free_text_walk_finds_the_columns_it_should() -> None:
    """A detector that quietly matched nothing would make the two assertions
    above pass vacuously, and a clean schema and a broken guard would look
    identical."""
    found = _free_text_columns_on_personal_tables()
    assert "work_history_entries.description" in found, "a Text column"
    assert "portal_handoffs.hard_stops" in found, "a JSON column"
    assert "user_profiles.headline" in found, "a String(255) column"
    # And it excludes what it should: encrypted columns, and short enums/ids.
    assert "user_profiles.email" not in found, "encrypted"
    assert "application_status_events.status" not in found, "String(32) enum value"
    assert "tracked_applications.user_id" not in found, "String(64) identifier"


def test_the_flag_and_encryption_checks_agree_on_the_known_column_set() -> None:
    """Pins the actual coverage, so an accidental mass-unflagging shows up as a
    number rather than as two empty sets agreeing with each other. The count is
    32 as of migration 0024: 28 from 0021, plus `tailored_cover_letter` and
    `application_status_events.note` (0023), plus `middle_name` and
    `preferred_name` (0024)."""
    assert _flagged() == _encrypted()
    assert len(_flagged()) == 32, (
        f"Sensitive column count changed to {len(_flagged())}. If that is "
        "intended, update this number — and check the new column also has a "
        "migration, a log-guard decision "
        "(tests/infrastructure/test_pii_log_call_sites.py), and a "
        "personal-data inventory category."
    )


def test_the_encrypted_type_base_is_what_this_file_thinks_it_is() -> None:
    """`_EncryptedColumn` is imported here as the shared base of the three
    concrete types. If a fourth type were added that did not inherit it, the
    tuple this file checks against would silently stop covering it."""
    for encrypted_type in _ENCRYPTED_TYPES:
        assert issubclass(encrypted_type, _EncryptedColumn)
