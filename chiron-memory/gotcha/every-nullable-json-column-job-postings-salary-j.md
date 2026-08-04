---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-80
type: gotcha
title: Every nullable JSON column (job_postings.salary, job_postings.requirements,…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/persistence/models.py, migrations/versions/0026_json_null_to_sql_null.py.
---
Every nullable JSON column (job_postings.salary, job_postings.requirements, education_entries.majors, education_entries.minors) was storing Python `None` as the JSON literal `null` rather than SQL `NULL`, because SQLAlchemy's default `JSON` type does this unless `none_as_null=True` is set.

## Why
This silently broke `WHERE requirements IS NULL` in `list_missing_requirements()`, meaning that query matched zero rows for every posting ever ingested — requirements extraction never found any work to do, on any posting, since the feature was built.

## Learned
This bug was initially misdiagnosed (by the assistant) as dev-database test-row accumulation causing a slow test to fail against a 1000-row limit; the real cause only surfaced once tests ran against a freshly-cleaned database and the failure persisted with just 44 rows. A structural guard test (test_json_null_semantics.py) now asserts every nullable JSON column declares none_as_null=True; it must import the models module (not just database.Base) or SQLAlchemy's metadata registry is empty and the guard passes vacuously.

## Where
src/infrastructure/persistence/models.py, migrations/versions/0026_json_null_to_sql_null.py.
