---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-96
type: convention
title: EmploymentType has a distinct NEW_GRAD member instead of folding new-grad roles into…
tags: [convention]
created: 2026-08-04
resource: src/domain/value_objects/employment_type.py
---
EmploymentType has a distinct NEW_GRAD member instead of folding new-grad roles into FULL_TIME

## Why
a junior wants neither and a graduating senior wants exactly that one; collapsing them makes that distinction unexpressible

## Where
src/domain/value_objects/employment_type.py
