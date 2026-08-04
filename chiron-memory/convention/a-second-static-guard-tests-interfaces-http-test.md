---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-9
type: convention
title: A second static guard (`tests/interfaces/http/test_no_pii_in_urls.py`) checks both the…
tags: [convention]
created: 2026-08-04
resource: tests/interfaces/http/test_no_pii_in_urls.py, frontend/src/api/client.ts
---
A second static guard (`tests/interfaces/http/test_no_pii_in_urls.py`) checks both the FastAPI route surface (via `app.openapi()`, not `app.routes`) and the frontend's URL-building templates for PII-shaped query/path parameter names

## Learned
any guard over 'is X ever logged/exposed' needs its own meta-test that plants a deliberate violation and asserts the guard catches it — a guard that silently stops matching (e.g. via a route-enumeration bug) looks identical to a clean codebase.

## Where
tests/interfaces/http/test_no_pii_in_urls.py, frontend/src/api/client.ts
