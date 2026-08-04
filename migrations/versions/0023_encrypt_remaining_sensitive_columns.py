"""encrypt the two sensitive columns migration 0021 missed

Found by the Epic 07 hardening pass (see docs/epic-07-hardening-check.md). Both
columns hold candidate free text and both sat in the clear beside an encrypted
column holding the same class of data:

* `job_applications.tailored_cover_letter` — a cover letter written from the
  candidate's profile, so their name, contact details and employment history in
  prose. `application_documents.content` holds exactly this and is encrypted;
  this column is that table's Epic 00/01 predecessor and was missed when the
  sensitive flags were drawn up.
* `application_status_events.note` — whatever the candidate typed about a status
  change. `application_reviews.submission_note` and
  `portal_handoffs.resolution_note` are the same kind of field and were both
  encrypted in 0021. Three free-text note columns had two different answers,
  which was an inconsistency rather than a distinction.

Mechanically the same as 0021, and deliberately so — read that migration's
docstring for the reasoning behind each step. Two differences worth knowing:

1. **`application_status_events` has a composite primary key**
   (`tracked_application_id`, `sequence`) with no surrogate id, so rows are
   addressed by both columns. 0021's helper assumed a single key column, which
   is why the row-addressing here is written out rather than reused.
2. **`note` carries a `server_default` of `''`** (added in 0020). It has to go:
   a server-side default on an encrypted column inserts plaintext that nothing
   can decrypt, which is the same trap 0021 documented for the other two note
   columns. The model's Python-side `default=""` takes over.

Neither column changes type — both were already `TEXT` — so this is purely a
data migration plus the dropped default.

Requires the encryption keys, for the same reason 0021 does: it encrypts with
the keyring the application uses, and anything else would write rows the
application cannot read. Idempotent per value (a row already carrying an
envelope is skipped), so an interrupted run can be re-run.

Reversible: `downgrade()` decrypts back to plaintext and restores the default.
It needs the same keys and opens the access scope any decryption requires,
naming itself as the subject.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-03 00:00:00.000000
"""

from collections.abc import Iterator
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Connection

from src.infrastructure.security.field_cipher import get_field_cipher
from src.infrastructure.security.sensitive_access import sensitive_data_access

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: How many rows are pulled into memory at a time. Matches 0021.
_BATCH_ROWS = 500

#: (table, column, primary-key columns). The key is a tuple because
#: `application_status_events` has no surrogate id — see the module docstring.
_COLUMNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("job_applications", "tailored_cover_letter", ("id",)),
    (
        "application_status_events",
        "note",
        ("tracked_application_id", "sequence"),
    ),
)


def _purpose(table: str, column: str) -> str:
    """Must match the `purpose` on the model's encrypted column exactly — it is
    authenticated into the ciphertext, so a mismatch here produces rows the
    application refuses to decrypt."""
    return f"{table}.{column}"


def upgrade() -> None:
    # Dropped before the rewrite so nothing inserted mid-migration lands as
    # plaintext under the old default.
    op.alter_column(
        "application_status_events",
        "note",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=None,
    )
    cipher = get_field_cipher()
    connection = op.get_bind()
    for table, column, key in _COLUMNS:
        purpose = _purpose(table, column)
        rewritten = 0
        for key_values, value in _iter_values(connection, table, column, key):
            if cipher.is_encrypted(value):
                # Already converted by an earlier, interrupted run.
                continue
            _write_value(
                connection,
                table,
                column,
                key,
                key_values,
                cipher.encrypt(value, purpose=purpose),
            )
            rewritten += 1
        print(f"  0023: encrypted {rewritten} value(s) in {purpose}")


def downgrade() -> None:
    with sensitive_data_access(
        subject="migration-0023",
        reason="decrypt sensitive columns back to plaintext on downgrade",
    ):
        cipher = get_field_cipher()
        connection = op.get_bind()
        for table, column, key in _COLUMNS:
            purpose = _purpose(table, column)
            rewritten = 0
            for key_values, value in _iter_values(connection, table, column, key):
                if not cipher.is_encrypted(value):
                    continue
                _write_value(
                    connection,
                    table,
                    column,
                    key,
                    key_values,
                    cipher.decrypt(value, purpose=purpose),
                )
                rewritten += 1
            print(f"  0023: decrypted {rewritten} value(s) in {purpose}")
    op.alter_column(
        "application_status_events",
        "note",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default="",
    )


def _iter_values(
    connection: Connection, table: str, column: str, key: tuple[str, ...]
) -> Iterator[tuple[tuple[object, ...], str]]:
    """Yield (primary-key values, current value) for every non-NULL row.

    Keyset-paginated on the primary key rather than `OFFSET`, so rewriting a row
    cannot shift the window and skip its neighbour. NULLs are skipped: a NULL
    stays a real NULL through encryption (see `_EncryptedColumn`), so "no cover
    letter yet" keeps meaning that rather than becoming ciphertext of nothing.
    """
    key_list = ", ".join(key)
    last: tuple[object, ...] | None = None
    while True:
        where = [f"{column} IS NOT NULL"]
        params: dict[str, object] = {"limit": _BATCH_ROWS}
        if last is not None:
            placeholders = ", ".join(f":k{index}" for index in range(len(key)))
            where.append(f"({key_list}) > ({placeholders})")
            params.update({f"k{index}": value for index, value in enumerate(last)})
        rows = connection.execute(
            sa.text(
                f"SELECT {key_list}, {column} FROM {table} "  # noqa: S608
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY {key_list} LIMIT :limit"
            ),
            params,
        ).fetchall()
        if not rows:
            return
        for row in rows:
            key_values = tuple(row[: len(key)])
            yield key_values, row[len(key)]
            last = key_values


def _write_value(
    connection: Connection,
    table: str,
    column: str,
    key: tuple[str, ...],
    key_values: tuple[object, ...],
    value: str,
) -> None:
    predicate = " AND ".join(f"{name} = :k{index}" for index, name in enumerate(key))
    params: dict[str, object] = {"value": value}
    params.update({f"k{index}": item for index, item in enumerate(key_values)})
    connection.execute(
        sa.text(
            f"UPDATE {table} SET {column} = :value WHERE {predicate}"  # noqa: S608
        ),
        params,
    )
