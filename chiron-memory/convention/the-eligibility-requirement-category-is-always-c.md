---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-108
type: convention
title: The ELIGIBILITY requirement category is always classified as hard, never soft
tags: [convention]
created: 2026-08-04
resource: src/domain/services/requirement_classifier.py
---
The ELIGIBILITY requirement category is always classified as hard, never soft

## Why
every other category can be phrased as a preference ("bachelor's preferred") but a rule about who may apply cannot be softened, so no soft branch exists for it

## Where
src/domain/services/requirement_classifier.py
