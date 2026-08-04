---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-63
type: convention
title: Sensitive/legally-attestable slots (work authorization, sponsorship, EEO, clearance) can…
tags: [convention]
created: 2026-08-04
resource: src/application/services/ats_form_field_planner.py, src/domain/value_objects/provenance_source.py (ATTESTING_SOURCES).
---
Sensitive/legally-attestable slots (work authorization, sponsorship, EEO, clearance) can never reach resolve_profile_field, and only ProvenanceSource.ANSWER (the user's own direct statement) is in ATTESTING_SOURCES, allowing that data to be asserted to an employer.

## Why
A parsed-from-resume or otherwise-derived value for these fields must not be usable as a legal declaration on the candidate's behalf.

## Learned
This is enforced structurally (a codebase-scanning test fails if any form-filling module can reach EEO data), not just by convention.

## Where
src/application/services/ats_form_field_planner.py, src/domain/value_objects/provenance_source.py (ATTESTING_SOURCES).
