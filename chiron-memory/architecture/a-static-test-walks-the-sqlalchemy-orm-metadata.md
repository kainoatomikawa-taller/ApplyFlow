---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-1
type: architecture
title: A static test walks the SQLAlchemy ORM metadata to compute which tables are transitively…
tags: [architecture]
created: 2026-08-04
resource: tests/infrastructure/test_personal_data_inventory_covers_schema.py
---
A static test walks the SQLAlchemy ORM metadata to compute which tables are transitively reachable from a user (via FK chains) and fails if any such table isn't declared in the personal-data inventory

## Learned
verified by planting a fake user-linked table in models.py — the guard correctly failed naming the undeclared table, and passed again after revert, confirming it actually enforces coverage on future schema changes.

## Where
tests/infrastructure/test_personal_data_inventory_covers_schema.py
