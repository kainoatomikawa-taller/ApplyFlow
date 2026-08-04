---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-29
type: decision
title: DSN-shaped settings (database_url, redis_url, celery_broker_url, celery_result_backend)…
tags: [decision]
created: 2026-08-04
resource: src/infrastructure/config.py (and all read sites: database.py, migrations/env.py, tasks/celery_app.py, tasks/ingestion_tasks.py)
---
DSN-shaped settings (database_url, redis_url, celery_broker_url, celery_result_backend) were plain `str` in config.py while every API key was already `SecretStr` — inconsistent.

## Why
DSNs embed credentials just like API keys and deserve the same protection from accidental logging via repr().

## Learned
added a guard test (test_every_credential_bearing_setting_is_a_secret_str) using suffix matching on setting names, not substring matching.

## Where
src/infrastructure/config.py (and all read sites: database.py, migrations/env.py, tasks/celery_app.py, tasks/ingestion_tasks.py)
