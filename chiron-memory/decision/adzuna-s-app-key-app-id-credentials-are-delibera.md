---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-7
type: decision
title: Adzuna's `app_key`/`app_id` credentials are deliberately left in the outbound request's…
tags: [decision]
created: 2026-08-04
resource: src/infrastructure/job_aggregators/adzuna_client.py
---
Adzuna's `app_key`/`app_id` credentials are deliberately left in the outbound request's query string and are not remediated

## Why
Adzuna's public API accepts no header-based alternative — this is an external API constraint, not something under this project's control

## Learned
the mitigation applied instead is that query strings are stripped from URLs before any exception/log line reaches a handler, so retry logging never leaks the key even though the outbound request still carries it.

## Where
src/infrastructure/job_aggregators/adzuna_client.py
