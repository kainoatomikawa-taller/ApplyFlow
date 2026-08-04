---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-68
type: gotcha
title: Skill matching in the fit score is exact string equality (lowercased/trimmed)
tags: [gotcha]
created: 2026-08-04
resource: src/domain/services/soft_preference_evaluator.py (_evaluate_skills).
---
Skill matching in the fit score is exact string equality (lowercased/trimmed) — "React" won't match "React.js", "Postgres" won't match "PostgreSQL".

## Why
No fuzzy/synonym matching exists for skills, unlike the deliberate broadening built for major dropdowns.

## Learned
Same class of problem as the major-dropdown matching issue, currently unfixed for skills — phrasing skills the way postings phrase them measurably affects match scores today.

## Where
src/domain/services/soft_preference_evaluator.py (_evaluate_skills).
