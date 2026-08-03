---
id: 644dfa30-a7db-462f-a43d-4999b3597642-9
type: gotcha
title: test_requirements_round_trip_against_a_real_database in…
tags: [gotcha]
created: 2026-08-03
resource: tests/infrastructure/test_job_posting_persistence_smoke.py
---
test_requirements_round_trip_against_a_real_database in test_job_posting_persistence_smoke.py fails independent of the encryption work — reproduced on stashed/pre-encryption code too.

## Why
the dev Postgres DB has ~1484 accumulated job_postings rows from repeated smoke-test runs, which likely breaks an assertion expecting an exact/small result set.

## Where
tests/infrastructure/test_job_posting_persistence_smoke.py
