---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-15
type: architecture
title: A dedicated `PersonalDataCoverageError` (application layer) is raised at runtime if the…
tags: [architecture]
created: 2026-08-04
resource: src/application/exceptions.py, checked by src/application/use_cases/export_user_data.py and erase_user_data.py against src/infrastructure/persistence/personal_data_store_impl.py.
---
A dedicated `PersonalDataCoverageError` (application layer) is raised at runtime if the personal-data store adapter's implemented categories diverge from the domain inventory's declared categories

## Why
complements the static schema-coverage test with a runtime guard, so a category declared in the domain but not wired into the SQL adapter (or vice versa) fails loudly instead of silently under-exporting/under-erasing

## Where
src/application/exceptions.py, checked by src/application/use_cases/export_user_data.py and erase_user_data.py against src/infrastructure/persistence/personal_data_store_impl.py.
