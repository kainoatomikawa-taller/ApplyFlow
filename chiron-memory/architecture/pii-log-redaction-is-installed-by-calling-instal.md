---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-1
type: architecture
title: PII log redaction is installed by calling `install_pii_redaction()` at four separate…
tags: [architecture]
created: 2026-08-04
resource: src/infrastructure/observability/logging_setup.py, src/interfaces/http/app.py, src/infrastructure/tasks/celery_app.py, src/interfaces/cli/main.py, tests/conftest.py
---
PII log redaction is installed by calling `install_pii_redaction()` at four separate process entry points: FastAPI app startup, Celery worker (via `celery_setup_logging` signal, honoring `--loglevel`), the CLI `main()`, and `tests/conftest.py`

## Why
there is no single process bootstrap shared by all four run modes, and `application/` layer code can't import `infrastructure/observability` without violating the dependency rule, so the factory must be installed at each outer entry point instead

## Learned
any new process entry point added later must also call `install_pii_redaction()` or it will log unredacted PII.

## Where
src/infrastructure/observability/logging_setup.py, src/interfaces/http/app.py, src/infrastructure/tasks/celery_app.py, src/interfaces/cli/main.py, tests/conftest.py
