---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-116
type: decision
title: DATA_ANALYTICS and DATA_SCIENCE are kept as separate JobFunction values even though…
tags: [decision]
created: 2026-08-04
resource: src/domain/value_objects/job_function.py
---
DATA_ANALYTICS and DATA_SCIENCE are kept as separate JobFunction values even though employers use the terms interchangeably.

## Why
the actual work and hiring bar differ between the two roles; a candidate wanting either can just select both.

## Where
src/domain/value_objects/job_function.py
