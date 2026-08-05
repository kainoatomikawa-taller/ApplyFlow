---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-130
type: gotcha
title: The `JobRequirementsOutput` DTO, its mapper, and the HTTP response were stale relative to…
tags: [gotcha]
created: 2026-08-05
resource: `src/application/dtos/job_requirements_dtos.py`, `src/application/mappers/job_requirements_mapper.py`.
---
The `JobRequirementsOutput` DTO, its mapper, and the HTTP response were stale relative to Phases 1–3 of the requirements schema — the employment-type, term, function, and standing fields existed in the domain value object but were never surfaced through the DTO/API layer.

## Learned
Domain model fields can be fully implemented and populated yet still invisible externally if the outbound DTO/mapper layer isn't updated in lockstep — check this layer whenever new domain fields are added.

## Where
`src/application/dtos/job_requirements_dtos.py`, `src/application/mappers/job_requirements_mapper.py`.
