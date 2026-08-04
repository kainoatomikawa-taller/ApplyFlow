---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-113
type: decision
title: JobFunction (kind-of-work taxonomy) was added as a new search preference field on the…
tags: [decision]
created: 2026-08-04
resource: src/domain/value_objects/job_function.py, JobSearchPreferences, filter, DTOs, frontend preferences section
---
JobFunction (kind-of-work taxonomy) was added as a new search preference field on the existing preferences section rather than as a separate endpoint/section.

## Why
a function is a search preference just like employment type and term - three independent axes of one question.

## Where
src/domain/value_objects/job_function.py, JobSearchPreferences, filter, DTOs, frontend preferences section
