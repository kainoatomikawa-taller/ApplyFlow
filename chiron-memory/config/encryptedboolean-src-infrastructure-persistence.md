---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-7
type: config
title: `EncryptedBoolean` (src/infrastructure/persistence/encrypted_types.py) must encrypt…
tags: [config]
created: 2026-08-04
resource: src/infrastructure/persistence/encrypted_types.py, migrations/versions/0021_encrypt_sensitive_columns.py.
---
`EncryptedBoolean` (src/infrastructure/persistence/encrypted_types.py) must encrypt booleans as the literal text Postgres' own `boolean::text` produces.

## Why
migration 0021 (encrypting sensitive columns, including work authorization/EEO fields) depends on that exact spelling matching; deviating breaks the migration's round-trip.

## Where
src/infrastructure/persistence/encrypted_types.py, migrations/versions/0021_encrypt_sensitive_columns.py.
