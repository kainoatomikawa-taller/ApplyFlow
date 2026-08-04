---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-39
type: convention
title: tests/infrastructure/test_pii_log_call_sites.py::test_every_sensitive_column_is_a_decided_…
tags: [convention]
created: 2026-08-04
---
tests/infrastructure/test_pii_log_call_sites.py::test_every_sensitive_column_is_a_decided_case requires every column flagged `sensitive` in models.py to have an explicit position in the log-call-site guard — either in BANNED_NAMES or in `_UNMATCHABLE_SENSITIVE_COLUMNS` with a documented reason.

## Why
mirrors test_sensitive_column_coverage's _REVIEWED_PLAINTEXT mechanism but for logging instead of encryption — closes the same 'never considered' gap class for a second control surface, so a newly-flagged sensitive column can't silently lack a log-safety decision.
