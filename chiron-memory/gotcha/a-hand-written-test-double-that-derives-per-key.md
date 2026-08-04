---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-40
type: gotcha
title: A hand-written test double that derives per-key encryption bytes from list position (e.g.…
tags: [gotcha]
created: 2026-08-04
resource: tests/infrastructure/test_encryption_at_rest.py
---
A hand-written test double that derives per-key encryption bytes from list position (e.g. `bytes([i]) * 32`) can silently assign identical key bytes to the same key_id across two different test keyrings, breaking envelope-decryption tests in a way that looks like a real bug.

## Learned
seed test keyrings by key_id/content, not by construction order, when a test needs multiple distinct keyrings referencing the same key ids.

## Where
tests/infrastructure/test_encryption_at_rest.py
