---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-10
type: gotcha
title: `tests/infrastructure/test_job_posting_persistence_smoke.py::test_requirements_round_trip_…
tags: [gotcha]
created: 2026-08-04
---
`tests/infrastructure/test_job_posting_persistence_smoke.py::test_requirements_round_trip_against_a_real_database` fails on a clean tree (confirmed via `git stash`) independent of this session's changes

## Why
recorded as a known pre-existing gotcha in project memory (`chiron-memory/gotcha/`)

## Learned
don't attribute this failure to new changes; verify against a stashed clean tree before investigating it as a regression.
