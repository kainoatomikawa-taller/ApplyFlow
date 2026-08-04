---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-107
type: decision
title: Eligibility requirements (e.g. "must be a current student") are enforced in…
tags: [decision]
created: 2026-08-04
resource: src/domain/services/hard_disqualifier_filter.py
---
Eligibility requirements (e.g. "must be a current student") are enforced in HardDisqualifierFilter, not the Phase 1 preference filter

## Why
eligibility is a demand the candidate meets or doesn't, same direction as degree/clearance checks — Phase 1's preference filter asks the opposite question (soft preferences)

## Where
src/domain/services/hard_disqualifier_filter.py
