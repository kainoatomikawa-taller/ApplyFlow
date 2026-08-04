---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-51
type: decision
title: Saving work authorization or EEO data records consent for…
tags: [decision]
created: 2026-08-04
resource: src/application/use_cases/save_work_authorization.py, save_eeo_self_identification.py.
---
Saving work authorization or EEO data records consent for ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE in the same request via an explicit `consent_acknowledged` checkbox field, rather than requiring a separate consent screen first or inferring consent implicitly.

## Why
Chosen (D6=Option C) to keep the flow to one form/one submit while still getting an explicit affirmative action (not just a PUT arriving), following the existing ErasureRequest.acknowledged precedent; consent is recorded before the profile write within the use case (not after), because 'granted consent but no data' is harmless while 'data stored but no consent record' is the bad failure mode.

## Learned
One ConsentPurpose (SENSITIVE_ATTRIBUTE_STORAGE) intentionally covers both work-authorization and EEO storage rather than being split in two, to avoid a domain enum + ledger migration for what was judged low value; clearing a sensitive section via null PUT does NOT withdraw previously granted consent — deletion and consent withdrawal are treated as distinct acts.

## Where
src/application/use_cases/save_work_authorization.py, save_eeo_self_identification.py.
