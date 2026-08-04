---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-81
type: config
title: PostgreSQL 15+ revokes CREATE on the `public` schema from any role that doesn't own the…
tags: [config]
created: 2026-08-04
resource: tests/conftest.py, applyflow_test database ownership.
---
PostgreSQL 15+ revokes CREATE on the `public` schema from any role that doesn't own the database, so a test database created under the developer's personal OS-user role (rather than the app's DB role) causes SQLAlchemy's create_all() to fail silently — and the affected real-database tests then silently *skip* instead of failing, which is easy to miss.

## Why
This nearly caused a fully-green test suite that was actually covering less than before (45 real-DB tests skipped) after introducing a separate `applyflow_test` database for isolation.

## Learned
The test DB must be created/owned by the same role the app itself uses (`applyflow`), and migrations should be applied to it to match production schema shape rather than relying on create_all alone.

## Where
tests/conftest.py, applyflow_test database ownership.
