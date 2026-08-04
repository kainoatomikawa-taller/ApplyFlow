---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-67
type: gotcha
title: The fit score is skills-dominant by accident, not by deliberate weighting
tags: [gotcha]
created: 2026-08-04
resource: src/domain/services/soft_preference_evaluator.py.
---
The fit score is skills-dominant by accident, not by deliberate weighting — skills contribute one scored item per skill the posting names (often 10+), while degree/clearance/experience contribute at most one item each.

## Why
No one chose this weighting; it fell out of how many items each category can produce per posting.

## Learned
This makes the score closer to "would this résumé survive a keyword search" (retrieval) than "how strong a candidate is this" (evaluation) — work history/job titles are never compared against the posting at all, only summed total years of experience.

## Where
src/domain/services/soft_preference_evaluator.py.
