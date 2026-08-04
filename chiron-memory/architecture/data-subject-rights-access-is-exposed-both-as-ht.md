---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-11
type: architecture
title: Data-subject-rights access is exposed both as HTTP endpoints (`/api/privacy/export`,…
tags: [architecture]
created: 2026-08-04
resource: src/interfaces/http/controllers/data_rights_controller.py, src/interfaces/cli/main.py.
---
Data-subject-rights access is exposed both as HTTP endpoints (`/api/privacy/export`, `/api/privacy/erasure`, `/api/privacy/consents`, `/api/privacy/consents/{purpose}`) and as CLI commands (`export-data`, `erase-data`)

## Why
a subject access/erasure request must be answerable even when the API/web UI can't be used directly (e.g. account already erased or user has no active session)

## Where
src/interfaces/http/controllers/data_rights_controller.py, src/interfaces/cli/main.py.
