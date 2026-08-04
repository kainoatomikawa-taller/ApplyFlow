---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-33
type: gotcha
title: Sensitive-field label recognition let sponsorship-*history* questions be answered with a…
tags: [gotcha]
created: 2026-08-04
resource: src/domain/services/ats_field_mapper.py
---
Sensitive-field label recognition let sponsorship-*history* questions be answered with a visa type, and "Work permit expiry date" be answered "Yes", instead of being surfaced as unattested sensitive data.

## Why
these were narrow token-matching gaps in `_LABEL_RULES`/`_asks_more_than_one_legal_question`; fixed by adding `until` (not `valid`, which also appears in legitimate current-state questions) to the matched tokens. Verified: reverting the fix breaks 6 tests.

## Where
src/domain/services/ats_field_mapper.py
