---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-64
type: architecture
title: Résumé import (parse_resume.py) merges parsed data into the profile field-by-field
tags: [architecture]
created: 2026-08-04
resource: src/application/use_cases/parse_resume.py (`_fill_contact_gaps`).
---
Résumé import (parse_resume.py) merges parsed data into the profile field-by-field: work history/education/skills use dedup-by-key merge; contact fields and address/links only fill gaps and never overwrite existing values; each contact/address/link group is all-or-nothing (single provenance source per group).

## Why
Merging a parsed value into a typed one would tag the result with whichever wrote last, mislabeling provenance for neither.

## Learned
Contact provenance is never downgraded when filling a gap — the existing stronger tag (e.g. user-typed) is kept even after a résumé fills in the phone, since there's no way to express "the name is mine, the phone is from my résumé" with one provenance tag per group.

## Where
src/application/use_cases/parse_resume.py (`_fill_contact_gaps`).
