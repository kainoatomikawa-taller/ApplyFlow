---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-4
type: convention
title: `EeoSelfIdentification` is flagged `SENSITIVE = True` at the domain value-object level…
tags: [convention]
created: 2026-08-04
resource: src/domain/value_objects/eeo_self_identification.py and src/infrastructure/persistence/models.py.
---
`EeoSelfIdentification` is flagged `SENSITIVE = True` at the domain value-object level and this is mirrored on the corresponding ORM columns.

## Why
keeps the sensitivity classification consistent across domain and persistence layers so encryption/handling can't silently diverge between them.

## Where
src/domain/value_objects/eeo_self_identification.py and src/infrastructure/persistence/models.py.
