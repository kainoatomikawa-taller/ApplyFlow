---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-9
type: convention
title: Acceptance-level enforcement tests for sensitive fields build profiles that round-trip…
tags: [convention]
created: 2026-08-04
resource: tests/acceptance/test_sensitive_field_enforcement.py.
---
Acceptance-level enforcement tests for sensitive fields build profiles that round-trip through the real persistence mappers (not just in-memory constructors) before running them through autofill, and assert on the actual bytes written to the page rather than on the internal report object.

## Why
catches encryption/decryption or mapping bugs that a purely in-memory fixture would miss, and avoids false confidence from asserting against the report when the report can diverge from what was truly written.

## Where
tests/acceptance/test_sensitive_field_enforcement.py.
