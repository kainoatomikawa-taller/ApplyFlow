---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-15
type: convention
title: The AST log-call-site guard's banned-name list is not limited to names synced from…
tags: [convention]
created: 2026-08-04
resource: tests/infrastructure/test_pii_log_call_sites.py
---
The AST log-call-site guard's banned-name list is not limited to names synced from `_SENSITIVE_COLUMN_INFO`-tagged ORM columns — bespoke non-column field names (e.g. `line`) were added manually after remediating log sites that quoted raw candidate/resume text via domain object attributes with no corresponding DB column

## Learned
when a remediated log site's leaked value came from a domain-object field rather than a persisted column, the guard's banned-name list needs a manual addition — the ORM-sync test alone won't catch it.

## Where
tests/infrastructure/test_pii_log_call_sites.py
