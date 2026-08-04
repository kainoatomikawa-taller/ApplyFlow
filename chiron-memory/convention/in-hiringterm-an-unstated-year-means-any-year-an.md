---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-97
type: convention
title: In HiringTerm, an unstated year means "any year" and still matches a specific-year…
tags: [convention]
created: 2026-08-04
resource: src/domain/value_objects/hiring_term.py
---
In HiringTerm, an unstated year means "any year" and still matches a specific-year preference (e.g. a posting saying just "Summer Intern" matches someone wanting Summer 2027)

## Why
hiding it would be indistinguishable from there being no matching posting — follows the project's existing rule that unknown is never held against the candidate

## Where
src/domain/value_objects/hiring_term.py
