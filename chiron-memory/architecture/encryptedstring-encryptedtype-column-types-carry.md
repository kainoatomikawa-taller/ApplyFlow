---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-25
type: architecture
title: EncryptedString/EncryptedType column types carry a `purpose` string (the `table.column`…
tags: [architecture]
created: 2026-08-04
resource: src/infrastructure/persistence/encrypted_types.py
---
EncryptedString/EncryptedType column types carry a `purpose` string (the `table.column` name) passed at construction and set `cache_ok = False`.

## Why
purpose varies per column instance, so caching two instances as one SQLAlchemy type-cache entry would be exactly the kind of column mix-up the purpose binding exists to prevent.

## Where
src/infrastructure/persistence/encrypted_types.py
