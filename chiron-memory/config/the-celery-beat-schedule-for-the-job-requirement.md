---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-131
type: config
title: The Celery beat schedule for the job-requirements sweep runs a batch size of 200 every 10…
tags: [config]
created: 2026-08-05
resource: `celery_app.py` beat_schedule, `job_requirements_sweep_batch_size`.
---
The Celery beat schedule for the job-requirements sweep runs a batch size of 200 every 10 minutes (~1,200 calls/hour), which is sized for draining a large backlog, not for steady-state incremental extraction of newly ingested postings.

## Why
once the backlog is cleared, this rate is unnecessarily aggressive for a trickle of new postings.

## Learned
worth lowering this batch size/frequency after the initial backlog is drained.

## Where
`celery_app.py` beat_schedule, `job_requirements_sweep_batch_size`.
