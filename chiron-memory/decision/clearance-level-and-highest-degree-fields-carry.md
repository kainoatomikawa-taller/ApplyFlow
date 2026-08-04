---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-69
type: decision
title: clearance_level and highest_degree fields carry no provenance tag (unlike work…
tags: [decision]
created: 2026-08-04
resource: src/domain/services/candidate_fact_extractor.py.
---
clearance_level and highest_degree fields carry no provenance tag (unlike work history/education/skills) and are deliberately excluded from candidate_fact_extractor.

## Why
Nothing can vouch for these as "facts" the way a work-history entry can, so a generated résumé/cover letter must not cite them as attested facts.

## Where
src/domain/services/candidate_fact_extractor.py.
