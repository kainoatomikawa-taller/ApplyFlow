---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-95
type: decision
title: Job-search preference matching (employment type, hiring term) got a new domain service…
tags: [decision]
created: 2026-08-04
resource: src/domain/services/job_search_preference_filter.py
---
Job-search preference matching (employment type, hiring term) got a new domain service JobSearchPreferenceFilter rather than extending HardDisqualifierFilter

## Why
HardDisqualifierFilter asks whether the candidate meets the posting's requirements; preferences ask the opposite — whether the posting matches what the candidate wants — merging them would produce a service that can't distinguish which kind of mismatch it found

## Where
src/domain/services/job_search_preference_filter.py
