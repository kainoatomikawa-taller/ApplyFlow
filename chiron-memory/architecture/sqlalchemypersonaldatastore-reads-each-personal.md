---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-16
type: architecture
title: `SqlAlchemyPersonalDataStore` reads each personal-data category generically via…
tags: [architecture]
created: 2026-08-04
resource: src/infrastructure/persistence/personal_data_store_impl.py.
---
`SqlAlchemyPersonalDataStore` reads each personal-data category generically via SQLAlchemy mapper reflection rather than one hand-written query per table, and erases across stores in FK-dependency order (children before parents)

## Why
avoids both per-table query duplication as categories grow and foreign-key constraint violations during multi-table erasure

## Where
src/infrastructure/persistence/personal_data_store_impl.py.
