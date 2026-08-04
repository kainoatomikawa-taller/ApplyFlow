---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-5
type: architecture
title: `AnswerApplicationField` (the use case that stores a candidate's own answer to a…
tags: [architecture]
created: 2026-08-04
resource: src/application/use_cases/answer_application_field.py.
---
`AnswerApplicationField` (the use case that stores a candidate's own answer to a surfaced/parked field) does not write to `AnswerMemory`.

## Why
prevents an EEO self-ID disclosure made on one application from being replayed/auto-suggested onto a later application — the exact harm the never-auto-filled rule exists to prevent.

## Where
src/application/use_cases/answer_application_field.py.
