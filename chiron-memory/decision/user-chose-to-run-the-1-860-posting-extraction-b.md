---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-127
type: decision
title: User chose to run the ~1,860-posting extraction backlog manually in bounded CLI chunks…
tags: [decision]
created: 2026-08-05
resource: `applyflow extract-requirements` CLI command.
---
User chose to run the ~1,860-posting extraction backlog manually in bounded CLI chunks (`applyflow extract-requirements --limit N`) rather than starting Celery beat to drain it automatically.

## Why
Each extraction call is an LLM call (~30s each) costing real money on the user's key — beat's 200-per-10-minutes schedule would burn through the whole backlog in ~1.6 hours with no checkpoint to inspect quality first, and full backlog at realistic per-call latency is ~16 hours of wall clock.

## Learned
For future backfills of this kind, prefer a bounded manual CLI entry point with `--dry-run` first over enabling the scheduled sweep directly.

## Where
`applyflow extract-requirements` CLI command.
