---
id: 644dfa30-a7db-462f-a43d-4999b3597642-8
type: gotcha
title: Persistence smoke tests touching sensitive-flagged columns need an autouse…
tags: [gotcha]
created: 2026-08-03
resource: tests/conftest.py
---
Persistence smoke tests touching sensitive-flagged columns need an autouse `sensitive_access` fixture (added to tests/conftest.py) providing a scope.

## Why
without it they fail with "Refusing to decrypt ... no sensitive-data access" now that fields are encrypted.

## Where
tests/conftest.py
