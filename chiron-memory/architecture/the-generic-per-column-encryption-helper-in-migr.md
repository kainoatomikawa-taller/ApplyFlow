---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-41
type: architecture
title: The generic per-column encryption helper in…
tags: [architecture]
created: 2026-08-04
resource: migrations/versions/0023_encrypt_remaining_sensitive_columns.py
---
The generic per-column encryption helper in migrations/versions/0021_encrypt_sensitive_columns.py only addresses rows by a single primary key; tables with composite keys (like application_status_events, keyed by application_id+sequence) needed a hand-rolled row-addressing variant in migration 0023 rather than reusing 0021's helper directly.

## Learned
future sensitive-column migrations on composite-key tables can't reuse the 0021 helper as-is.

## Where
migrations/versions/0023_encrypt_remaining_sensitive_columns.py
