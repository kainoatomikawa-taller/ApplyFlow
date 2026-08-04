---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-99
type: architecture
title: JobRequirements is persisted as a JSON column, so adding new fields (employment_type,…
tags: [architecture]
created: 2026-08-04
resource: src/infrastructure/persistence/job_posting_repository_impl.py, migrations/versions/0027_add_job_search_preferences.py
---
JobRequirements is persisted as a JSON column, so adding new fields (employment_type, hiring_term) to it required no migration; JobSearchPreferences on UserProfile needed explicit columns and migration 0027 since profile fields are relational

## Where
src/infrastructure/persistence/job_posting_repository_impl.py, migrations/versions/0027_add_job_search_preferences.py
