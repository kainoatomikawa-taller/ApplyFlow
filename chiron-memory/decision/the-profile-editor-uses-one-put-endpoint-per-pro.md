---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-50
type: decision
title: The profile editor uses one PUT endpoint per profile section (~18 endpoints total) rather…
tags: [decision]
created: 2026-08-04
resource: src/interfaces/http/controllers/profile_controller.py.
---
The profile editor uses one PUT endpoint per profile section (~18 endpoints total) rather than a single whole-profile PUT.

## Why
Chosen (D1=Option B) so sensitive fields (work authorization, EEO) don't travel over the wire on unrelated edits (e.g. fixing a phone number), each sensitive section gets its own permission/audit boundary, and two browser tabs editing different sections can't clobber each other — at the cost of more endpoints than a single PUT.

## Learned
No ETag/version token was needed as a result — per-section idempotent PUTs (full replace, nulls = clear) made optimistic-concurrency handling unnecessary.

## Where
src/interfaces/http/controllers/profile_controller.py.
