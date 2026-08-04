---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-14
type: gotcha
title: Epic 05's own acceptance-check doc (`docs/epic-05-acceptance-check.md`) explicitly states…
tags: [gotcha]
created: 2026-08-04
resource: docs/epic-05-acceptance-check.md, src/domain/entities/application_review.py.
---
Epic 05's own acceptance-check doc (`docs/epic-05-acceptance-check.md`) explicitly states the review screen was NOT covered by that check.

## Why
the review-screen path (ReviewedAnswer/FieldSensitivity, application_review.py) had never been exercised end-to-end for sensitive-field correctness until this verification task added coverage for it.

## Where
docs/epic-05-acceptance-check.md, src/domain/entities/application_review.py.
