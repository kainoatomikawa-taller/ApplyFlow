---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-82
type: gotcha
title: Real-database smoke tests (tests/infrastructure/test_*_persistence_smoke.py) connect…
tags: [gotcha]
created: 2026-08-04
resource: tests/conftest.py now overrides DATABASE_URL to point at a separate `applyflow_test` database before any `src` module is imported (must happen at that exact point, since src/infrastructure/persistence/database.py builds its SQLAlchemy engine at import time off an lru_cached settings object — setting the env var after import has no effect).
---
Real-database smoke tests (tests/infrastructure/test_*_persistence_smoke.py) connect directly to the live DATABASE_URL — the actual dev database — and never clean up after themselves, accumulating roughly 44 rows per full pytest run.

## Why
Left unaddressed, this pollutes match-quality evaluation (junk postings like "Smoke Test Co" mixed with real ones) and causes tests referencing real user data to accumulate hundreds of fake profiles over time.

## Where
tests/conftest.py now overrides DATABASE_URL to point at a separate `applyflow_test` database before any `src` module is imported (must happen at that exact point, since src/infrastructure/persistence/database.py builds its SQLAlchemy engine at import time off an lru_cached settings object — setting the env var after import has no effect).
