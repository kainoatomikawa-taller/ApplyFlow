---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-55
type: gotcha
title: models.py:346 references docs/decisions/0002-encryption-at-rest.md, but that ADR file…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/persistence/models.py:346, docs/decisions/.
---
models.py:346 references docs/decisions/0002-encryption-at-rest.md, but that ADR file doesn't exist — the decisions folder jumps from 0001 straight to 0003.

## Why
Encryption-at-rest is arguably the largest architectural decision in the codebase, yet it has no ADR documenting it, unlike smaller decisions that do.

## Learned
A code comment citing a doc path doesn't guarantee the doc exists — dangling doc references can hide undocumented decisions on exactly the areas that most need documentation.

## Where
src/infrastructure/persistence/models.py:346, docs/decisions/.
