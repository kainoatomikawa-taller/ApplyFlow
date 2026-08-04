---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-10
type: convention
title: An AST-based static guard test style (proving a sensitive value object like EEO is…
tags: [convention]
created: 2026-08-04
resource: tests/infrastructure/test_pii_log_call_sites.py, tests/acceptance/test_sensitive_field_enforcement.py.
---
An AST-based static guard test style (proving a sensitive value object like EEO is unreachable from any module outside the profile and its persistence mapping) follows the existing precedent set by `tests/infrastructure/test_pii_log_call_sites.py`.

## Why
reuses an established pattern for statically proving a sensitive-data invariant holds everywhere, rather than relying only on runtime tests that can't cover every call site.

## Where
tests/infrastructure/test_pii_log_call_sites.py, tests/acceptance/test_sensitive_field_enforcement.py.
