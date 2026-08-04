---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-2
type: gotcha
title: Sponsorship-history questions (e.g. "Have you ever been sponsored for a visa?") on…
tags: [gotcha]
created: 2026-08-04
resource: src/application/services/ats_form_field_planner.py (`_TEXT_VALUE_KINDS` handling).
---
Sponsorship-history questions (e.g. "Have you ever been sponsored for a visa?") on select/radio widgets are correctly surfaced, but the same class of question rendered as a text input can get a visa type (e.g. "H-1B") or "Yes" written in incorrectly (e.g. for "Work permit expiry date").

## Why
the sensitive-field guard logic differentiates by widget kind and isn't uniformly applied to text-input fields.

## Learned
these were found and routed for a follow-up fix (not fixed in this task, per explicit user scope decision) — treat as an open gap, not resolved.

## Where
src/application/services/ats_form_field_planner.py (`_TEXT_VALUE_KINDS` handling).
