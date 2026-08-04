---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-112
type: convention
title: When a candidate has no *stated* completed degree, the hard disqualifier filter does not…
tags: [convention]
created: 2026-08-04
resource: src/domain/services/hard_disqualifier_filter.py, tests/domain/test_education_standing_filtering.py
---
When a candidate has no *stated* completed degree, the hard disqualifier filter does not disqualify them from postings requiring "must have graduated"

## Why
absence of a stated fact can't prove a negative (the candidate may just not have filled it in yet) — the filter only disqualifies on provable failure to meet a requirement, consistently across all requirement categories, not just education

## Where
src/domain/services/hard_disqualifier_filter.py, tests/domain/test_education_standing_filtering.py
