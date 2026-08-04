---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-19
type: gotcha
title: Two docstring-referenced guard tests…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/persistence/models.py, src/infrastructure/persistence/encrypted_types.py
---
Two docstring-referenced guard tests (tests/infrastructure/test_sensitive_column_coverage.py and test_encryption_at_rest.py) did not actually exist despite models.py, encrypted_types.py, and eight smoke tests naming them as the safety net.

## Why
because the smoke tests referencing them all open an access scope themselves, the suite stayed green even with the actual guards missing — a docstring claim is not proof a test exists.

## Learned
verify any test a docstring/comment claims exists before trusting it as coverage; both were rewritten and mutation-tested (8/8 planted defects caught).

## Where
src/infrastructure/persistence/models.py, src/infrastructure/persistence/encrypted_types.py
