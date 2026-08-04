---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-100
type: gotcha
title: A test (test_sensitive_column_coverage.py) fails automatically whenever a new free-text…
tags: [gotcha]
created: 2026-08-04
resource: tests/infrastructure/test_sensitive_column_coverage.py
---
A test (test_sensitive_column_coverage.py) fails automatically whenever a new free-text column is added to a table holding personal data, until the column is explicitly reviewed/flagged or encrypted · Why/

## Learned
it's a deliberate guard against silently-unencrypted PII columns, not a bug — new profile/posting text columns must be triaged in that test file

## Where
tests/infrastructure/test_sensitive_column_coverage.py
