---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-0
type: architecture
title: Data-subject rights (export, erasure) are built on top of a single declared personal-data…
tags: [architecture]
created: 2026-08-04
resource: src/domain/services/personal_data_inventory.py, consumed by src/application/use_cases/export_user_data.py and erase_user_data.py
---
Data-subject rights (export, erasure) are built on top of a single declared personal-data inventory service that enumerates every personal-data category, its store, lawful basis, and export/erasure disposition, rather than each use case hardcoding its own table list

## Learned
this is what makes export/erasure complete-by-construction as the schema grows, instead of complete-by-diligence.

## Where
src/domain/services/personal_data_inventory.py, consumed by src/application/use_cases/export_user_data.py and erase_user_data.py
