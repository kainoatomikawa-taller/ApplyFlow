---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-47
type: gotcha
title: Adding a database migration for an encrypted column must never set a server_default.
tags: [gotcha]
created: 2026-08-04
resource: migrations/versions/*.py, src/infrastructure/persistence/encrypted_types.py.
---
Adding a database migration for an encrypted column must never set a server_default.

## Why
A server-side default on an encrypted column stores a value that was never passed through the app's encryption layer, so nothing can decrypt it later — this already bit migrations 0021 and 0023, both of which had to drop a default they'd added.

## Learned
New sensitive/PII columns should be added nullable with no default, never backfilled via server_default.

## Where
migrations/versions/*.py, src/infrastructure/persistence/encrypted_types.py.
