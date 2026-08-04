---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-0
type: gotcha
title: The label recognizer in `src/domain/services/ats_field_mapper.py` (`_LABEL_RULES`)…
tags: [gotcha]
created: 2026-08-04
resource: src/domain/services/ats_field_mapper.py.
---
The label recognizer in `src/domain/services/ats_field_mapper.py` (`_LABEL_RULES`) matched the compound phrase "Are you legally authorized to work in the US without sponsorship?" to the sponsorship slot instead of refusing it, causing ApplyFlow to write the exact opposite of the truth for both citizens and sponsorship-needing candidates.

## Why
rule ordering picked one of two matching sensitive slots instead of detecting the conflict; neither the mapper's rule ordering nor the planner's checkbox-exclusion logic covered this compound-wording case.

## Learned
a label matching two mutually exclusive legal-attestation slots must be surfaced for the candidate, never silently resolved by rule precedence.

## Where
src/domain/services/ats_field_mapper.py.
