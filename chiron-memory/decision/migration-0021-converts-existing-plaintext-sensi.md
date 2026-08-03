---
id: 644dfa30-a7db-462f-a43d-4999b3597642-6
type: decision
title: Migration 0021 converts existing plaintext sensitive columns to ciphertext in place, with…
tags: [decision]
created: 2026-08-03
resource: migrations/versions/0021_encrypt_sensitive_columns.py
---
Migration 0021 converts existing plaintext sensitive columns to ciphertext in place, with a downgrade that fully restores original plaintext, column types, and the blind index.

## Why
retrofitting encryption later is painful (per task framing), so migration correctness was verified end-to-end against a real Postgres scratch DB seeded with plaintext rows rather than only unit-tested.

## Where
migrations/versions/0021_encrypt_sensitive_columns.py
