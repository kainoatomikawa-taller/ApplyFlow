---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-22
type: gotcha
title: Columns with a `server_default` must have that default dropped as part of the migration…
tags: [gotcha]
created: 2026-08-04
resource: migrations/versions/0021_encrypt_sensitive_columns.py, migrations/versions/0023_encrypt_remaining_sensitive_columns.py
---
Columns with a `server_default` must have that default dropped as part of the migration that converts them to encrypted ciphertext-as-text, per the pattern documented in migrations/versions/0021_encrypt_sensitive_columns.py.

## Why
a server_default written against the old plaintext type would silently write plaintext defaults into an otherwise-encrypted column.

## Learned
`application_status_events.note` had exactly this trap (server_default="") and needed the same fix as 0021's documented columns.

## Where
migrations/versions/0021_encrypt_sensitive_columns.py, migrations/versions/0023_encrypt_remaining_sensitive_columns.py
