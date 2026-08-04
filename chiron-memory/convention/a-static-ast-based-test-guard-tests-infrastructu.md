---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-8
type: convention
title: A static AST-based test guard (`tests/infrastructure/test_pii_log_call_sites.py`) scans…
tags: [convention]
created: 2026-08-04
resource: tests/infrastructure/test_pii_log_call_sites.py
---
A static AST-based test guard (`tests/infrastructure/test_pii_log_call_sites.py`) scans every `logger.*()` call in `src/` and fails if a banned PII/sensitive field name appears in the log arguments, format string, or an f-string used as the message; violations can be allowlisted per line with a mandatory `# pii-ok: <reason>` comment

## Why
establishes an enforced baseline so new code can't reintroduce PII logging silently

## Learned
the guard's banned-name list is deliberately kept in sync with the ORM's `_SENSITIVE_COLUMN_INFO`-tagged columns (src/infrastructure/persistence/models.py) via a companion test, so adding a new sensitive column forces an explicit decision about the log guard.

## Where
tests/infrastructure/test_pii_log_call_sites.py
