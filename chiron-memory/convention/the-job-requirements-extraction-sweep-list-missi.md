---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-128
type: convention
title: The job-requirements extraction sweep (`list_missing_requirements`) only selects postings…
tags: [convention]
created: 2026-08-05
resource: `list_missing_requirements()` in the job posting repository.
---
The job-requirements extraction sweep (`list_missing_requirements`) only selects postings with `requirements IS NULL`, so re-running extraction (via CLI or beat) is always safe/idempotent — an interrupted run resumes and a finished posting is never re-extracted or paid for twice.

## Learned
No need for manual tracking of 'already processed' postings when scripting backfills against this table.

## Where
`list_missing_requirements()` in the job posting repository.
