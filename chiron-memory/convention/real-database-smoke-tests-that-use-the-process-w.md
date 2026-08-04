---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-6
type: convention
title: Real-database smoke tests that use the process-wide async engine must use a…
tags: [convention]
created: 2026-08-04
resource: pattern used across tests/infrastructure/*_persistence_smoke.py, followed in test_data_rights_persistence_smoke.py.
---
Real-database smoke tests that use the process-wide async engine must use a `schema_ready` fixture that disposes the engine's connection pool before the test's event loop runs

## Why
pooled connections are bound to the event loop that opened them, which differs from a given test's loop, causing cross-loop errors

## Where
pattern used across tests/infrastructure/*_persistence_smoke.py, followed in test_data_rights_persistence_smoke.py.
