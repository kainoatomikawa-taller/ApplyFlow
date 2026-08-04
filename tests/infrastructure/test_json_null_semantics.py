"""Guard: every nullable JSON column must store Python `None` as SQL NULL.

Why this guard exists
---------------------
SQLAlchemy's `JSON` type serializes Python `None` into the JSON literal `null`
unless constructed with `none_as_null=True`. `null` is a *value*, so
`WHERE column IS NULL` does not match it.

That defect sat in `job_postings.requirements` undetected. Every posting stored
`null` rather than SQL NULL, so `list_missing_requirements()` — the query the
requirement-extraction sweep uses to find postings still needing a pass —
returned an empty list for every posting ever ingested. Nothing was ever
extracted, and the degree, clearance, skill and experience logic that reads
requirements ran against nothing on real data.

It was invisible for two reasons worth remembering: the only test that could see
it was failing for an unrelated-looking reason and had been written off as a
local-database quirk, and every *unit* test builds entities in memory where the
distinction does not exist.

A static assertion over the metadata rather than a database round-trip: it needs
no Postgres, it covers columns no test happens to exercise, and it fails when a
new JSON column is added without the decision being made.
"""

from __future__ import annotations

from sqlalchemy import JSON

# `models` must be imported for its side effect, not for a name: `Base.metadata`
# is empty until the module defining the tables has been executed. Without this
# the guard finds zero columns and passes vacuously — which is why
# `test_the_guard_has_something_to_check` exists below.
import src.infrastructure.persistence.models  # noqa: F401
from src.infrastructure.persistence.database import Base


def _nullable_json_columns() -> list[tuple[str, str, JSON]]:
    found: list[tuple[str, str, JSON]] = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, JSON) and column.nullable:
                found.append((table.name, column.name, column.type))
    return found


def test_the_guard_has_something_to_check() -> None:
    """A guard that silently stops finding columns looks exactly like a clean
    codebase, so it asserts it found some first."""
    assert len(_nullable_json_columns()) >= 4


def test_every_nullable_json_column_stores_none_as_sql_null() -> None:
    offenders = [
        f"{table}.{column}"
        for table, column, json_type in _nullable_json_columns()
        if json_type.none_as_null is not True
    ]
    assert not offenders, (
        "These nullable JSON columns serialize Python None as the JSON literal "
        f"'null' rather than SQL NULL: {offenders}. A query filtering them with "
        "IS NULL will match nothing. Declare them as JSON(none_as_null=True) — "
        "and if a column genuinely needs to store JSON null as a distinct value, "
        "say so here explicitly rather than leaving it to the default."
    )


def test_requirements_is_covered_by_name() -> None:
    """Named explicitly because it is the column the defect actually broke, and
    the one a future refactor is most likely to redeclare."""
    requirements = Base.metadata.tables["job_postings"].columns["requirements"]
    assert isinstance(requirements.type, JSON)
    assert requirements.type.none_as_null is True
