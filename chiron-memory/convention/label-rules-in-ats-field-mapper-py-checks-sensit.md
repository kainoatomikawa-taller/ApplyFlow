---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-34
type: convention
title: `_LABEL_RULES` in ats_field_mapper.py checks sensitive-field label rules first, ahead of…
tags: [convention]
created: 2026-08-04
resource: src/domain/services/ats_field_mapper.py
---
`_LABEL_RULES` in ats_field_mapper.py checks sensitive-field label rules first, ahead of all other field-recognition rules.

## Why
ensures a label matching both a sensitive slot and something else is always treated as the higher-stakes sensitive case.

## Where
src/domain/services/ats_field_mapper.py
