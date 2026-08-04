---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-8
type: gotcha
title: `tests/infrastructure/test_job_posting_persistence_smoke.py::test_requirements_round_trip_…
tags: [gotcha]
created: 2026-08-04
resource: tests/infrastructure/test_job_posting_persistence_smoke.py.
---
`tests/infrastructure/test_job_posting_persistence_smoke.py::test_requirements_round_trip_against_a_real_database` fails pre-existing and unrelated to sensitive-field work — a dev-DB row-accumulation issue.

## Why
documented in project memory already; do not treat this failure as a regression caused by sensitive-field or other unrelated changes.

## Where
tests/infrastructure/test_job_posting_persistence_smoke.py.
