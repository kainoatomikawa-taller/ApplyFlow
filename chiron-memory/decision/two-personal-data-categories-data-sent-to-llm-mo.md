---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-4
type: decision
title: Two personal-data categories
tags: [decision]
created: 2026-08-04
resource: src/domain/services/personal_data_inventory.py.
---
Two personal-data categories — data sent to LLM model providers, and copies of submitted applications held by employers — are declared in the inventory but explicitly marked as deferred/out of ApplyFlow's control, surfaced in the export output and erasure receipt rather than silently omitted

## Where
src/domain/services/personal_data_inventory.py.
