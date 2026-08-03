"""encrypt sensitive columns at rest

Turns every sensitive-flagged column in the schema from plaintext into
AES-256-GCM ciphertext (Epic 07). Three things happen per column, in this order,
and the order matters:

1. **Retype to text.** Ciphertext has no length and no shape, so
   `String(32)`, `Boolean`, and `JSON` all become `TEXT`. Postgres does the
   conversion itself with `USING column::text`, which is why the boolean and
   JSON columns arrive at step 2 already spelled the way this codebase's
   encrypted types spell them (`true`/`false`, compact JSON) — see
   `EncryptedBoolean` for why that spelling had to be matched rather than
   chosen.
2. **Encrypt in place.** Every existing row is read, encrypted under the
   configured active key, and written back. This is a real data migration, not
   a schema-only one: without it the columns would be typed for ciphertext and
   still hold cleartext, and the application would refuse to read them (by
   design — see `FieldCipher.decrypt`, which raises rather than passing an
   unrecognized value through).
3. **Drop server defaults.** `application_reviews.submission_note` and
   `portal_handoffs.resolution_note` defaulted to `''` in the database. A
   server-side default on an encrypted column inserts plaintext that nothing
   can decrypt, so the default has to live on the Python side alone.

Also adds `job_applications.candidate_email_bidx` — the blind index that keeps
`list_by_candidate` working now that the address itself is unqueryable — and
backfills it for existing rows. The old plaintext index on `candidate_email` is
dropped: an index on randomized ciphertext can serve no query.

Requires the encryption keys
----------------------------
This migration encrypts with the same keyring the application uses
(`FIELD_ENCRYPTION_KEYS`, or the development fallback when unset), because
anything else would write rows the application cannot read. So it has to run
with the target environment's key configuration present. That is a deliberate
coupling of a migration to the config layer rather than a hidden one: the
alternative is a migration that appears to succeed and leaves a database of
unreadable rows.

Batched at `_BATCH_ROWS` per table so a large table is not read into memory at
once, and idempotent per value — a row that already carries an envelope is
skipped, so an interrupted run can be re-run.

Reversible
----------
`downgrade()` decrypts back to plaintext and restores the original column
types. It needs the same keys for the same reason, and it needs the access
scope the application requires for any decryption — the migration opens one
explicitly, naming itself as the subject.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-03 00:00:00.000000
"""

from collections.abc import Iterator
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Connection

from src.infrastructure.persistence.job_application_repository_impl import (
    email_blind_index,
)
from src.infrastructure.security.field_cipher import get_field_cipher
from src.infrastructure.security.sensitive_access import sensitive_data_access

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: How many rows are pulled into memory at a time while re-writing a column.
_BATCH_ROWS = 500


class _Col:
    """One column to convert: where it is, how it was typed, and how the
    plaintext has to be spelled so the application's encrypted type recognizes
    it after decryption.

    `original_type` is only used by `downgrade()`; `postgres_cast` is the
    expression that turns the old type into text on the way up, and the one
    that turns text back into the old type on the way down.
    """

    def __init__(
        self,
        table: str,
        column: str,
        key: str,
        original_type: sa.types.TypeEngine[object],
        *,
        nullable: bool = True,
    ) -> None:
        self.table = table
        self.column = column
        #: The primary-key column(s) used to address a row while rewriting it.
        self.key = key
        self.original_type = original_type
        self.nullable = nullable

    @property
    def purpose(self) -> str:
        """Must match the `purpose` on the model's encrypted column exactly —
        it is authenticated into the ciphertext, so a mismatch here produces
        rows the application refuses to decrypt."""
        return f"{self.table}.{self.column}"


#: Every sensitive-flagged column in the schema, in dependency-free order.
#: Mirrors `_SENSITIVE_COLUMN_INFO` in `models.py`; the coverage test
#: (`tests/infrastructure/test_sensitive_column_coverage.py`) is what keeps the
#: two from drifting, by failing if a flagged column is not encrypted.
_COLUMNS: tuple[_Col, ...] = (
    # Contact info (Epic 07 extends Epic 01's flags to cover it — see
    # `UserProfileModel`).
    _Col("user_profiles", "full_name", "id", sa.String(255), nullable=False),
    _Col("user_profiles", "email", "id", sa.String(320), nullable=False),
    _Col("user_profiles", "phone", "id", sa.String(32)),
    _Col("user_profiles", "location", "id", sa.String(255)),
    _Col("user_profiles", "street_address", "id", sa.String(255)),
    _Col("user_profiles", "city", "id", sa.String(255)),
    _Col("user_profiles", "state_or_region", "id", sa.String(255)),
    _Col("user_profiles", "postal_code", "id", sa.String(32)),
    _Col("user_profiles", "country", "id", sa.String(255)),
    # Citizenship / work authorization.
    _Col("work_authorizations", "status", "profile_id", sa.String(32), nullable=False),
    _Col("work_authorizations", "citizenship_country", "profile_id", sa.String(255)),
    _Col("work_authorizations", "visa_type", "profile_id", sa.String(64)),
    _Col("work_authorizations", "requires_sponsorship", "profile_id", sa.Boolean()),
    _Col("work_authorizations", "details", "profile_id", sa.Text()),
    # EEO self-identification.
    _Col("eeo_self_identifications", "gender_identity", "profile_id", sa.String(32)),
    _Col("eeo_self_identifications", "race_ethnicity", "profile_id", sa.String(64)),
    _Col("eeo_self_identifications", "veteran_status", "profile_id", sa.String(32)),
    _Col("eeo_self_identifications", "disability_status", "profile_id", sa.String(32)),
    # Remembered application answers, and the embedding derived from them.
    _Col("answer_memories", "question_text", "id", sa.Text(), nullable=False),
    _Col("answer_memories", "answer_text", "id", sa.Text(), nullable=False),
    _Col("answer_memories", "embedding", "id", sa.JSON(), nullable=False),
    # Uploaded resumes.
    _Col("resumes", "original_filename", "id", sa.String(255), nullable=False),
    _Col("resumes", "extracted_text", "id", sa.Text(), nullable=False),
    # The documents actually sent to employers.
    _Col("application_documents", "content", "id", sa.Text(), nullable=False),
    # In-flight application reviews.
    _Col("application_reviews", "answers", "id", sa.JSON(), nullable=False),
    _Col("application_reviews", "submission_note", "id", sa.Text(), nullable=False),
    # Portal hand-offs.
    _Col("portal_handoffs", "resolution_note", "id", sa.Text(), nullable=False),
    # Contact info on the original application record.
    _Col("job_applications", "candidate_email", "id", sa.String(320), nullable=False),
)

#: Columns whose database-side default has to go, because a server default on an
#: encrypted column writes plaintext. The Python-side `default=""` on the model
#: takes over.
_SERVER_DEFAULTS_TO_DROP = (
    ("application_reviews", "submission_note"),
    ("portal_handoffs", "resolution_note"),
)


def upgrade() -> None:
    for col in _COLUMNS:
        # `postgresql_using` is what lets a Boolean or JSON column become text
        # without a temporary column: Postgres rewrites each value with the
        # cast as part of the ALTER.
        op.alter_column(
            col.table,
            col.column,
            type_=sa.Text(),
            existing_type=col.original_type,
            existing_nullable=col.nullable,
            postgresql_using=f"{col.column}::text",
        )
    for table, column in _SERVER_DEFAULTS_TO_DROP:
        op.alter_column(table, column, existing_type=sa.Text(), server_default=None)

    # Added before the backfill so the same pass can fill it: the blind index is
    # derived from the address, which is still readable at this point in the
    # loop below (it is read, encrypted, and written back in one step).
    op.add_column(
        "job_applications",
        sa.Column(
            "candidate_email_bidx",
            sa.String(length=64),
            nullable=True,
            comment=(
                "Blind index (keyed HMAC-SHA256) of candidate_email — the "
                "lookup key for the encrypted column. See "
                "src/infrastructure/security/field_cipher.py."
            ),
        ),
    )

    _encrypt_existing_rows()

    # NOT NULL only after the backfill, so an existing table is not rejected
    # mid-migration for rows that had not been filled yet.
    op.alter_column(
        "job_applications",
        "candidate_email_bidx",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_index(
        "ix_job_applications_candidate_email_bidx",
        "job_applications",
        ["candidate_email_bidx"],
    )
    # The plaintext index cannot serve a query against randomized ciphertext.
    op.drop_index("ix_job_applications_candidate_email", table_name="job_applications")


def downgrade() -> None:
    op.drop_index(
        "ix_job_applications_candidate_email_bidx", table_name="job_applications"
    )
    op.drop_column("job_applications", "candidate_email_bidx")

    _decrypt_existing_rows()

    for col in reversed(_COLUMNS):
        op.alter_column(
            col.table,
            col.column,
            type_=col.original_type,
            existing_type=sa.Text(),
            existing_nullable=col.nullable,
            postgresql_using=_downgrade_cast(col),
        )
    for table, column in _SERVER_DEFAULTS_TO_DROP:
        op.alter_column(table, column, existing_type=sa.Text(), server_default="")
    op.create_index(
        "ix_job_applications_candidate_email", "job_applications", ["candidate_email"]
    )


def _downgrade_cast(col: _Col) -> str:
    """How decrypted text becomes the original type again.

    `String(n)` needs no `USING` clause at all (Postgres narrows text to varchar
    on its own, and will refuse rather than truncate if some value grew past
    `n` while the column was text — which is the behaviour to want). `Boolean`
    and `JSON` need an explicit cast, and both accept exactly the spelling the
    encrypted types write.
    """
    if isinstance(col.original_type, sa.Boolean):
        return f"{col.column}::boolean"
    if isinstance(col.original_type, sa.JSON):
        return f"{col.column}::json"
    return col.column


def _encrypt_existing_rows() -> None:
    """Rewrite every plaintext value as ciphertext, then fill the blind index."""
    cipher = get_field_cipher()
    connection = op.get_bind()
    for col in _COLUMNS:
        rewritten = 0
        for key, value in _iter_values(connection, col):
            if cipher.is_encrypted(value):
                # Already converted by an earlier, interrupted run.
                continue
            _write_value(
                connection, col, key, cipher.encrypt(value, purpose=col.purpose)
            )
            rewritten += 1
        print(f"  0021: encrypted {rewritten} value(s) in {col.purpose}")
    _backfill_email_blind_index(connection)


def _backfill_email_blind_index(connection: Connection) -> None:
    """Fill `candidate_email_bidx` from the (now encrypted) address column.

    Runs after the addresses have been encrypted, so it decrypts to compute the
    digest rather than reading the plaintext it could have captured a moment
    earlier. That is one extra step and one fewer way to be wrong: it goes
    through the same cipher and the same access gate the application does, and
    calls the very function (`email_blind_index`) that `list_by_candidate` will
    call, so a lookup cannot miss a row this migration wrote.
    """
    with sensitive_data_access(
        subject="migration-0021",
        reason="backfill the candidate_email blind index from encrypted rows",
    ):
        cipher = get_field_cipher()
        rows = connection.execute(
            sa.text(
                "SELECT id, candidate_email FROM job_applications "
                "WHERE candidate_email_bidx IS NULL"
            )
        ).fetchall()
        for row_id, envelope in rows:
            address = cipher.decrypt(
                envelope, purpose="job_applications.candidate_email"
            )
            connection.execute(
                sa.text(
                    "UPDATE job_applications SET candidate_email_bidx = :bidx "
                    "WHERE id = :id"
                ),
                {"bidx": email_blind_index(address), "id": row_id},
            )
        print(f"  0021: filled {len(rows)} candidate_email blind index value(s)")


def _decrypt_existing_rows() -> None:
    """The inverse of `_encrypt_existing_rows`, for `downgrade()`."""
    cipher = get_field_cipher()
    connection = op.get_bind()
    with sensitive_data_access(
        subject="migration-0021",
        reason="decrypt sensitive columns back to plaintext for a downgrade",
    ):
        for col in _COLUMNS:
            for key, value in _iter_values(connection, col):
                if not cipher.is_encrypted(value):
                    continue
                _write_value(
                    connection, col, key, cipher.decrypt(value, purpose=col.purpose)
                )


def _write_value(connection: Connection, col: _Col, key: str, value: str) -> None:
    # Table/column names are interpolated because they are identifiers, which
    # cannot be bound parameters; every one of them comes from the `_COLUMNS`
    # literal above, never from input. The value itself is always bound.
    connection.execute(
        sa.text(
            f"UPDATE {col.table} SET {col.column} = :value "  # noqa: S608
            f"WHERE {col.key} = :key"
        ),
        {"value": value, "key": key},
    )


def _iter_values(connection: Connection, col: _Col) -> Iterator[tuple[str, str]]:
    """Yield `(key, value)` for every non-NULL value in `col`, in batches.

    NULLs are skipped rather than encrypted: a NULL means "not provided" and
    stays one (see `_EncryptedColumn`). Paginates on the primary key rather than
    with OFFSET, so a table's scan cost does not grow with each batch — and
    because the rows are being rewritten as they are read, an OFFSET would be
    walking a moving target.
    """
    last_key: str | None = None
    while True:
        query = (
            f"SELECT {col.key}, {col.column} FROM {col.table} "  # noqa: S608
            f"WHERE {col.column} IS NOT NULL"
            + (f" AND {col.key} > :last_key" if last_key is not None else "")
            + f" ORDER BY {col.key} LIMIT {_BATCH_ROWS}"
        )
        params = {"last_key": last_key} if last_key is not None else {}
        rows = connection.execute(sa.text(query), params).fetchall()
        if not rows:
            return
        for key, value in rows:
            yield key, value
        last_key = rows[-1][0]
