---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-28
type: gotcha
title: `DEBUG` defaults to `True` in Settings and previously drove SQLAlchemy's `echo=`, which…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/persistence/database.py, src/infrastructure/config.py
---
`DEBUG` defaults to `True` in Settings and previously drove SQLAlchemy's `echo=`, which logs full bound-parameter tuples (shapeless data the pattern-based PII redactor cannot recognize as PII since it has no key names or recognizable shape).

## Why
a forgotten `DEBUG=false` in production would have written whole candidate records to logs past every other redaction control. Fixed: SQL echo is now gated on `environment == "development"` specifically, not on DEBUG alone, and made unit-testable rather than an inline expression.

## Where
src/infrastructure/persistence/database.py, src/infrastructure/config.py
