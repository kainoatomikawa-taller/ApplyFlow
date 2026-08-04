---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-2
type: decision
title: Consent-withdrawal ledger entries survive a user's data erasure
tags: [decision]
created: 2026-08-04
resource: src/infrastructure/persistence/personal_data_store_impl.py — the consent category has a reader but deliberately no eraser.
---
Consent-withdrawal ledger entries survive a user's data erasure — only the event (purpose, granted/withdrawn, timestamp, notice/policy version, account id) is kept, with no PII fields

## Why
GDPR Art. 7(1) requires being able to demonstrate consent history, and the withdrawal that triggered an erasure is the most relevant record to retain

## Where
src/infrastructure/persistence/personal_data_store_impl.py — the consent category has a reader but deliberately no eraser.
