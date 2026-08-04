---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-3
type: architecture
title: `decide_sensitive_field` in src/domain/services/sensitive_field_policy.py is the single…
tags: [architecture]
created: 2026-08-04
resource: src/domain/services/sensitive_field_policy.py.
---
`decide_sensitive_field` in src/domain/services/sensitive_field_policy.py is the single place in the codebase that decides what, if anything, ApplyFlow puts into a sensitive field on an application form.

## Why
centralizes the two opposite rules — work-authorization/sponsorship must always be exactly accurate, EEO self-ID must never be auto-filled — so no other code path can drift from them.

## Where
src/domain/services/sensitive_field_policy.py.
