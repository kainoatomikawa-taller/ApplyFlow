---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-26
type: gotcha
title: The PII log redactor did not catch credentials embedded in DSN-style URLs (e.g.…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/observability/pii_redaction.py
---
The PII log redactor did not catch credentials embedded in DSN-style URLs (e.g. `postgresql://user:password@host`, `redis://:password@host`) or the labelled `database_url=postgresql://...` form.

## Why
this repo's own smoke-test skip message stringifies a DSN, so this gap was directly reachable in real logs. Fixed by adding a userinfo-credential rule that must run before the email rule (ordering matters — see _RULES).

## Where
src/infrastructure/observability/pii_redaction.py
