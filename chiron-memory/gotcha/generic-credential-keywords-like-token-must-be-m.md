---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-3
type: gotcha
title: Generic credential keywords (like `token`) must be matched as exact snake_case suffixes,…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/observability/pii_redaction.py
---
Generic credential keywords (like `token`) must be matched as exact snake_case suffixes, not as substrings/wildcards, in the PII/secret redaction rules

## Why
a wildcard match on `token` redacted `cache_read_input_tokens=500`, destroying LLM cost telemetry in logs

## Learned
when adding new sensitive-keyword patterns to the redactor, always test against existing non-PII log lines that happen to contain the keyword as a substring (e.g. cost/telemetry fields) before shipping.

## Where
src/infrastructure/observability/pii_redaction.py
