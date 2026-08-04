---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-4
type: decision
title: The `/api/applications` list endpoint no longer accepts `candidate_email` as a query…
tags: [decision]
created: 2026-08-04
resource: src/interfaces/http/controllers/application_controller.py, src/interfaces/http/dependencies.py, frontend/src/App.tsx, frontend/src/api/client.ts
---
The `/api/applications` list endpoint no longer accepts `candidate_email` as a query parameter; it derives the candidate identity from the verified bearer token's `email` claim, and requests with no `email` claim get a 400

## Why
ApplyFlow is a single-user application (per prior architecture memory), so the token's own identity was the only legitimate value that parameter could ever carry — passing it as a query string was both a PII leak and a de facto authorization hole (any caller could request any other candidate's applications by URL)

## Learned
don't relocate a PII query param into a header/body — check first whether the value should just be removed and derived from the authenticated identity.

## Where
src/interfaces/http/controllers/application_controller.py, src/interfaces/http/dependencies.py, frontend/src/App.tsx, frontend/src/api/client.ts
