---
id: 644dfa30-a7db-462f-a43d-4999b3597642-3
type: architecture
title: Since encrypted email can't be queried directly, a deterministic blind index…
tags: [architecture]
created: 2026-08-03
resource: src/infrastructure/persistence/job_application_repository_impl.py
---
Since encrypted email can't be queried directly, a deterministic blind index (email_blind_index(), stored in candidate_email_bidx) is derived from a separate FIELD_BLIND_INDEX_KEY to allow equality lookups against ciphertext-backed email.

## Where
src/infrastructure/persistence/job_application_repository_impl.py
