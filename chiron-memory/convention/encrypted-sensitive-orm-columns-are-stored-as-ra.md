---
id: 644dfa30-a7db-462f-a43d-4999b3597642-2
type: convention
title: Encrypted/sensitive ORM columns are stored as raw SQL Text regardless of their logical…
tags: [convention]
created: 2026-08-03
resource: src/infrastructure/persistence/models.py
---
Encrypted/sensitive ORM columns are stored as raw SQL Text regardless of their logical type (bool, JSON, string).

## Why
the column holds an opaque ciphertext envelope, not the plaintext type.

## Where
src/infrastructure/persistence/models.py
