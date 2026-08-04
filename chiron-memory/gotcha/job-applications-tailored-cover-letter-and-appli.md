---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-20
type: gotcha
title: job_applications.tailored_cover_letter and application_status_events.note were plaintext…
tags: [gotcha]
created: 2026-08-04
resource: fixed via migrations/versions/0023_encrypt_remaining_sensitive_columns.py and src/infrastructure/persistence/models.py
---
job_applications.tailored_cover_letter and application_status_events.note were plaintext free-text columns holding personal data while sibling columns of the same class (application_documents.content, other status-event notes) were encrypted.

## Why
nothing enforced that every free-text column on a personal-data table gets a sensitive-flag decision — the lockstep coverage guard only checked columns someone remembered to flag.

## Learned
encryption coverage audits must diff 'columns that should be flagged' against 'columns that are flagged', not just check flagged==encrypted.

## Where
fixed via migrations/versions/0023_encrypt_remaining_sensitive_columns.py and src/infrastructure/persistence/models.py
