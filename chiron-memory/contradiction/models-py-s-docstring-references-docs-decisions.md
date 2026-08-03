---
id: 644dfa30-a7db-462f-a43d-4999b3597642-7
type: contradiction
title: models.py's docstring references docs/decisions/0002-encryption-at-rest.md for the…
tags: [contradiction]
created: 2026-08-03
resource: src/infrastructure/persistence/models.py
---
models.py's docstring references docs/decisions/0002-encryption-at-rest.md for the encryption design rationale, but that file was never created.

## Learned
this reference is currently dangling and needs the decision doc written to resolve.

## Where
src/infrastructure/persistence/models.py
