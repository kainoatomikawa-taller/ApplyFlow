---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-98
type: gotcha
title: mypy in this project targets Python 3.11, so PEP 695 generic syntax (e.g. `def…
tags: [gotcha]
created: 2026-08-04
resource: src/domain/value_objects/job_search_preferences.py
---
mypy in this project targets Python 3.11, so PEP 695 generic syntax (e.g. `def f[T](...)`) fails type-checking · Why/

## Learned
use an explicit TypeVar instead of the new generic syntax

## Where
src/domain/value_objects/job_search_preferences.py
