---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-5
type: decision
title: `GenerationGuardAudit` no longer logs the verbatim stripped resume line
tags: [decision]
created: 2026-08-04
resource: src/application/services/generation_guard_audit.py, src/domain/services/provenance_guard.py (`ProvenanceViolation` docstring corrected — it has no `line_number` field)
---
`GenerationGuardAudit` no longer logs the verbatim stripped resume line; it logs only `unsupported_terms` (the specific fabricated claim terms)

## Why
the prior docstring's reasoning — that a provenance-stripped line is entirely model invention and therefore safe/useful to log in full — doesn't hold, since a line is stripped for containing an unsupported *claim*, not because every word in it is fabricated; logging the full line could expose a real candidate name/detail sitting next to an invented achievement

## Learned
when a docstring justifies logging raw content by an invariant, re-derive whether that invariant actually holds before trusting it as a PII safety argument.

## Where
src/application/services/generation_guard_audit.py, src/domain/services/provenance_guard.py (`ProvenanceViolation` docstring corrected — it has no `line_number` field)
