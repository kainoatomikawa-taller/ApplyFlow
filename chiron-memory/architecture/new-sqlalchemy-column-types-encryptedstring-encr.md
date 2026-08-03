---
id: 644dfa30-a7db-462f-a43d-4999b3597642-1
type: architecture
title: New SQLAlchemy column types (EncryptedString/EncryptedBoolean/EncryptedJson) wrap…
tags: [architecture]
created: 2026-08-03
resource: src/infrastructure/persistence/encrypted_types.py
---
New SQLAlchemy column types (EncryptedString/EncryptedBoolean/EncryptedJson) wrap FieldCipher so ORM models declare encryption at the column-type level.

## Where
src/infrastructure/persistence/encrypted_types.py
