---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-21
type: convention
title: The new test_sensitive_column_coverage.py requires every free-text/JSON column on a…
tags: [convention]
created: 2026-08-04
resource: tests/infrastructure/test_sensitive_column_coverage.py
---
The new test_sensitive_column_coverage.py requires every free-text/JSON column on a personal-data table to be either encrypted or listed in `_REVIEWED_PLAINTEXT` with a documented reason.

## Why
closes the class of gap where a column is simply never considered rather than deliberately left plaintext.

## Where
tests/infrastructure/test_sensitive_column_coverage.py
