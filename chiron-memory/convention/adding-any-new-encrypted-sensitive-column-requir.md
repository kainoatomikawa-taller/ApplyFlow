---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-48
type: convention
title: Adding any new encrypted/sensitive column requires six coordinated changes
tags: [convention]
created: 2026-08-04
resource: src/infrastructure/persistence/models.py, profile_repository_impl.py, migrations/versions/, tests/infrastructure/test_pii_log_call_sites.py, tests/infrastructure/test_sensitive_column_coverage.py.
---
Adding any new encrypted/sensitive column requires six coordinated changes: the ORM model column (with sensitive info/comment markers), repository mapper (both directions), an alembic migration (nullable, no default, verified up and down against real Postgres), the PII log-guard's banned-name list, the sensitive-column-count pin test, and confirming the table is covered in the personal-data inventory.

## Why
The codebase enforces this via multiple static tests so no sensitive column can silently skip encryption, logging safety, or documentation.

## Learned
Budget for all six steps whenever a task description says 'just add a column' for anything PII-like; skipping the log-guard or count-pin update fails CI even if the migration itself is correct.

## Where
src/infrastructure/persistence/models.py, profile_repository_impl.py, migrations/versions/, tests/infrastructure/test_pii_log_call_sites.py, tests/infrastructure/test_sensitive_column_coverage.py.
