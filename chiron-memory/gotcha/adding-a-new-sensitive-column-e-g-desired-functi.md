---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-120
type: gotcha
title: Adding a new sensitive column (e.g. desired_functions) trips a column guard test that…
tags: [gotcha]
created: 2026-08-04
resource: tests/infrastructure/test_sensitive_column*.py.
---
Adding a new sensitive column (e.g. desired_functions) trips a column guard test that must be explicitly updated/ruled on.

## Learned
expect this test to fail whenever a new profile column is added and requires a deliberate ruling, not a blanket allow.

## Where
tests/infrastructure/test_sensitive_column*.py.
