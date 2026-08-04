---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-62
type: gotcha
title: The ATS field planner/mapper has no concept of repeated field groups
tags: [gotcha]
created: 2026-08-04
resource: src/application/services/ats_field_mapper.py and the planner.
---
The ATS field planner/mapper has no concept of repeated field groups — a form with "Major 1"/"Major 2" dropdowns (double major) or "School 1"/"School 2" both map to the same flat slot and both receive the same joined value or the same latest entry, rather than being zipped index-wise against the list.

## Why
The slot enum is flat with one value per concept and no index awareness; this is a real gap, not a small patch.

## Learned
When a double major collapses onto a single-choice dropdown, ApplyFlow now flags it as inferred (not just verbatim) since a real choice was made and the other major is unrepresented.

## Where
src/application/services/ats_field_mapper.py and the planner.
