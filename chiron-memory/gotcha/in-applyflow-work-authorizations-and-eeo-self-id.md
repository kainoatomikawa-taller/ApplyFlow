---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-44
type: gotcha
title: In ApplyFlow, work_authorizations and eeo_self_identifications were never writable in…
tags: [gotcha]
created: 2026-08-04
resource: src/application/use_cases/parse_resume.py; no src/interfaces/http/controllers/profile_controller.py existed before this work.
---
In ApplyFlow, work_authorizations and eeo_self_identifications were never writable in production even though the full sensitive-field decision engine (13-case work-authorization truth table, EEO never-autofill rule, encryption) was fully built and tested.

## Why
The only profile writer was ParseResume, whose ParsedResumeData DTO has no authorization/EEO fields, and there was no profile controller/endpoint at all — the 118-case acceptance suite passed because it builds profiles directly in memory, bypassing the missing write path entirely.

## Learned
Prose/tests asserting a feature works can hide the fact that no real caller can ever reach it — always check reachability from an actual entry point, not just unit coverage.

## Where
src/application/use_cases/parse_resume.py; no src/interfaces/http/controllers/profile_controller.py existed before this work.
