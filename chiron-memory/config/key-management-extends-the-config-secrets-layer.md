---
id: 644dfa30-a7db-462f-a43d-4999b3597642-4
type: config
title: Key management extends the config/secrets layer with FIELD_ENCRYPTION_KEYS and…
tags: [config]
created: 2026-08-03
resource: src/infrastructure/config.py, documented in .env.example.
---
Key management extends the config/secrets layer with FIELD_ENCRYPTION_KEYS and FIELD_BLIND_INDEX_KEY env vars, required whenever ENVIRONMENT is not "development".

## Why
mirrors how SUPABASE_JWT_SECRET is already enforced outside development.

## Where
src/infrastructure/config.py, documented in .env.example.
