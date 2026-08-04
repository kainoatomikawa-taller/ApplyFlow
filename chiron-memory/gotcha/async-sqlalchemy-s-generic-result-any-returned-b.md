---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-9
type: gotcha
title: Async SQLAlchemy's generic `Result[Any]` returned by `execute()` on a DELETE statement…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/persistence/personal_data_store_impl.py.
---
Async SQLAlchemy's generic `Result[Any]` returned by `execute()` on a DELETE statement does not type as having `.rowcount` under mypy strict; the concrete `CursorResult` type must be used to access it

## Where
src/infrastructure/persistence/personal_data_store_impl.py.
