---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-124
type: gotcha
title: Extraction machinery (use case, LLM extractor, Celery task, beat schedule) fully existed…
tags: [gotcha]
created: 2026-08-05
resource: `src/infrastructure/tasks/requirements_tasks.py`, `celery_app.py` beat_schedule.
---
Extraction machinery (use case, LLM extractor, Celery task, beat schedule) fully existed but had never actually run against real data.

## Why
A Celery *worker* was running (executes tasks) but Celery *beat* (schedules/enqueues them on the 10-minute schedule) was never started, so nothing ever triggered the task.

## Learned
worker running != beat running; check both before assuming a scheduled task pipeline is live.

## Where
`src/infrastructure/tasks/requirements_tasks.py`, `celery_app.py` beat_schedule.
