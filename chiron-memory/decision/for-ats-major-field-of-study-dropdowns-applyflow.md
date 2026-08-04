---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-60
type: decision
title: For ATS major/field-of-study dropdowns, ApplyFlow selects the exact major if listed, and…
tags: [decision]
created: 2026-08-04
resource: src/domain/services/subject_option_matcher.py, applied from src/application/services/ats_form_field_planner.py.
---
For ATS major/field-of-study dropdowns, ApplyFlow selects the exact major if listed, and only broadens to a category (e.g. Applied Mathematics → Mathematics) if the exact value isn't an option.

## Why
User requirement was strict "if and only if" — broadening should never override an exact match, and a wrong broadening would misstate the user's major.

## Learned
Verified via mutation testing that moving broadening ahead of the exact-match pass breaks the requirement, so exact-first ordering is load-bearing, not incidental.

## Where
src/domain/services/subject_option_matcher.py, applied from src/application/services/ats_form_field_planner.py.
