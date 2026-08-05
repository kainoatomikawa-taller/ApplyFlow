---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-129
type: gotcha
title: There was no `--re-extract` path for job requirements
tags: [gotcha]
created: 2026-08-05
resource: `applyflow extract-requirements --re-extract` flag.
---
There was no `--re-extract` path for job requirements — once a posting had non-null requirements, the sweep/CLI would always skip it, even after the extraction prompt changes.

## Why
needed so that future prompt/schema changes to extraction don't leave stale requirements stuck forever with no way to refresh them.

## Learned
Added proactively before it was needed, since 0 postings were extracted at the time — worth keeping in mind that this flag exists for the next prompt revision.

## Where
`applyflow extract-requirements --re-extract` flag.
