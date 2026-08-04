"""Convert the JSON literal `null` to SQL NULL in every nullable JSON column.

The bug this repairs
--------------------
SQLAlchemy's `JSON` type serializes Python `None` into the JSON literal `null`
unless told otherwise, and `null` is a *value*: `WHERE requirements IS NULL` does
not match it. So `list_missing_requirements()` — the query the requirement
extraction sweep uses to find postings still needing a pass — returned an empty
list for every posting that had ever been ingested. Requirements were never
extracted for anything, and every filter and score that reads them (degree,
clearance, skills, experience) therefore ran against nothing on real data.

The models now declare `JSON(none_as_null=True)`, which fixes new writes. This
migration fixes the rows already stored.

`salary`, `majors` and `minors` are converted too. Only `requirements` is queried
for NULL today, so only it was actually broken — but leaving the other three
holding a JSON `null` keeps the same trap armed for the next query someone writes
against them.

Reversible in shape but not worth reversing: the downgrade puts the JSON literal
back, because that is what the previous code wrote, and a downgrade that left SQL
NULLs behind would leave the old code reading a state it never produced.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

#: (table, column) pairs holding nullable JSON where `None` means "absent".
_JSON_COLUMNS: tuple[tuple[str, str], ...] = (
    ("job_postings", "requirements"),
    ("job_postings", "salary"),
    ("education_entries", "majors"),
    ("education_entries", "minors"),
)


def upgrade() -> None:
    for table, column in _JSON_COLUMNS:
        # `::text = 'null'` rather than a json operator so this works whether the
        # column is `json` or `jsonb`, and touches only rows actually holding the
        # literal — a row with real content is left alone.
        op.execute(
            f"UPDATE {table} SET {column} = NULL "  # noqa: S608 - fixed identifiers
            f"WHERE {column} IS NOT NULL AND {column}::text = 'null'"
        )


def downgrade() -> None:
    for table, column in _JSON_COLUMNS:
        op.execute(
            f"UPDATE {table} SET {column} = 'null'::json "  # noqa: S608
            f"WHERE {column} IS NULL"
        )
