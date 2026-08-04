---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-2
type: gotcha
title: On the installed FastAPI version (0.141), `app.routes` contains `_IncludedRouter` wrapper…
tags: [gotcha]
created: 2026-08-04
resource: tests/interfaces/http/test_no_pii_in_urls.py
---
On the installed FastAPI version (0.141), `app.routes` contains `_IncludedRouter` wrapper objects, not flattened `APIRoute`s, so `isinstance(route, APIRoute)` filtering over `app.routes` silently matches zero routes

## Why
discovered when a first draft of the URL/query-param PII guard passed vacuously (0 routes scanned) instead of failing

## Learned
to enumerate the real route/query-param surface, call `app.openapi()` and read `spec['paths']` rather than walking `app.routes` directly; any static guard over FastAPI routes needs a meta-test asserting it actually sees a nonzero, expected set of routes/params.

## Where
tests/interfaces/http/test_no_pii_in_urls.py
