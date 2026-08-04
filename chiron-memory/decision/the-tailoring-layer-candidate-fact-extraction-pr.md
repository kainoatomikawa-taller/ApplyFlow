---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-11
type: decision
title: The tailoring layer (candidate fact extraction / provenance fact assembly used to…
tags: [decision]
created: 2026-08-04
resource: src/domain/services/candidate_fact_extractor.py, src/application/services/provenance_fact_assembler.py.
---
The tailoring layer (candidate fact extraction / provenance fact assembly used to generate resumes and cover letters) had no field-level policy object protecting it from EEO leakage — the exclusion of EEO data was correct behavior already but was previously untested.

## Why
unlike autofill (protected by `decide_sensitive_field`) and the review screen (protected by `FieldSensitivity`), tailoring's correctness relied on EEO simply never being included in the fact corpus, an implicit rather than enforced guarantee.

## Learned
this was the genuine coverage gap found during verification; regression tests were added rather than new production code, since behavior was already correct.

## Where
src/domain/services/candidate_fact_extractor.py, src/application/services/provenance_fact_assembler.py.
