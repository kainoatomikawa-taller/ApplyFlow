---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-78
type: decision
title: Cross-source duplicate postings (the same job appearing via both Adzuna and a direct…
tags: [decision]
created: 2026-08-04
resource: src/application/use_cases/ingest_board_jobs.py.
---
Cross-source duplicate postings (the same job appearing via both Adzuna and a direct board ingest) are deliberately left as separate rows — dedup is scoped per-source only.

## Why
Deciding which source's version should win is a separate concern from ingesting either one; documented as an explicit tradeoff rather than solved silently.

## Where
src/application/use_cases/ingest_board_jobs.py.
