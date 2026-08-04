---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-6
type: convention
title: `ReviewedAnswer` tracks field sensitivity via a `FieldSensitivity` enum distinguishing…
tags: [convention]
created: 2026-08-04
resource: src/domain/value_objects/reviewed_answer.py, src/domain/entities/application_review.py.
---
`ReviewedAnswer` tracks field sensitivity via a `FieldSensitivity` enum distinguishing `LEGAL_ATTESTATION` (work authorization/sponsorship) from voluntary self-ID (`is_voluntary_self_id` property), plus separately who put the answer there.

## Why
the review screen needs to answer two different questions — is this legally binding, and did the candidate choose to disclose it — which are not the same axis.

## Where
src/domain/value_objects/reviewed_answer.py, src/domain/entities/application_review.py.
