---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-27
type: gotcha
title: The sensitive-key-name matcher for redaction only matched `api_key` (underscore), not…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/observability/pii_redaction.py (_SENSITIVE_KEY wildcard/suffix name lists)
---
The sensitive-key-name matcher for redaction only matched `api_key` (underscore), not `x-api-key` (hyphen) headers.

## Learned
key-name matching needs hyphenated variants alongside underscore variants, not just one convention.

## Where
src/infrastructure/observability/pii_redaction.py (_SENSITIVE_KEY wildcard/suffix name lists)
