---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-3
type: decision
title: Consent purposes are modeled and recorded (RecordConsent/ListUserConsents use cases,…
tags: [decision]
created: 2026-08-04
resource: documented as an ordered next step in docs/decisions/0004-gdpr-ccpa-groundwork.md.
---
Consent purposes are modeled and recorded (RecordConsent/ListUserConsents use cases, consent_decisions table) but NOT yet enforced at the point of processing (matching, tailoring, autofill, etc.)

## Why
gating six existing use cases on consent would each need its own behavior change, tests, and user-facing explanation — kept out of scope of the data-rights groundwork commit

## Where
documented as an ordered next step in docs/decisions/0004-gdpr-ccpa-groundwork.md.
