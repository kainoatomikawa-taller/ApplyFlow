---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-66
type: architecture
title: Job matching is two distinct stages with different semantics
tags: [architecture]
created: 2026-08-04
resource: src/domain/services/hard_disqualifier_filter.py, src/domain/services/soft_preference_evaluator.py.
---
Job matching is two distinct stages with different semantics: a hard disqualifier filter (degree, clearance, location, work authorization only — never skills/work-history/education) that can remove a job from the list, and a soft preference evaluator that computes a 0–100 fit score as (met preferences / total judged preferences).

## Why
Keeping disqualification narrow to only provable mismatches avoids wrongly filtering out jobs; the score is a plain ratio with no weighting.

## Learned
Both hard filters and the score treat an unset/unjudgeable field as "not counted" rather than "failed" — unknown is never held against the candidate, a principle applied consistently throughout matching.

## Where
src/domain/services/hard_disqualifier_filter.py, src/domain/services/soft_preference_evaluator.py.
