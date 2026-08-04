---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-115
type: decision
title: JobFunction enum has no OTHER member.
tags: [decision]
created: 2026-08-04
resource: src/domain/value_objects/job_function.py
---
JobFunction enum has no OTHER member.

## Why
an 'other' bucket would be selectable and would just filter to postings sharing nothing but being unrecognized; None already means 'could not tell' and unknown values never narrow results.

## Where
src/domain/value_objects/job_function.py
