---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-123
type: gotcha
title: All 1,947 ingested job postings had `requirements` stored as the JSON literal `null`…
tags: [gotcha]
created: 2026-08-05
resource: fixed via migration 0026.
---
All 1,947 ingested job postings had `requirements` stored as the JSON literal `null` instead of true SQL `NULL`, so `list_missing_requirements()` (which filters on `requirements IS NULL`) matched zero rows for every posting ever ingested.

## Why
The extraction sweep silently found nothing pending and reported success, masking the fact that extraction had never run.

## Learned
A 'no rows found, no error' sweep result can mean 'truly done' or 'query can never match' — verify the storage representation matches the query's null semantics.

## Where
fixed via migration 0026.
