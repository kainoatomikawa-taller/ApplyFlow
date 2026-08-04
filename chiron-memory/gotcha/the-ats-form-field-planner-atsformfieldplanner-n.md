---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-52
type: gotcha
title: The ATS form-field planner (AtsFormFieldPlanner) never consulted FormField.required…
tags: [gotcha]
created: 2026-08-04
resource: src/application/services/ats_form_field_planner.py (_plan_value_field).
---
The ATS form-field planner (AtsFormFieldPlanner) never consulted FormField.required before this work — it treated every unanswerable field the same whether the portal marked it required or not.

## Why
This mattered once blank-optional-fields (like middle name) needed to mean 'no value, don't ask' — but a required field with no value is a genuine conflict that must still be surfaced to the user, not silently left blank.

## Learned
Any feature that wants to treat an empty/absent profile value as a deliberate answer (vs. 'unanswered, ask me') must add required-awareness to the planner, since it wasn't there by default.

## Where
src/application/services/ats_form_field_planner.py (_plan_value_field).
