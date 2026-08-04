---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-18
type: convention
title: Every key in `Settings` (src/infrastructure/config.py) must also be documented in…
tags: [convention]
created: 2026-08-04
resource: tests/infrastructure/test_config.py::test_env_example_documents_every_key_without_real_values.
---
Every key in `Settings` (src/infrastructure/config.py) must also be documented in `.env.example`, enforced by a dedicated test

## Why
`test_env_example_documents_every_key_without_real_values` failed the moment `PRIVACY_POLICY_VERSION` was added to Settings without a matching .env.example entry

## Where
tests/infrastructure/test_config.py::test_env_example_documents_every_key_without_real_values.
