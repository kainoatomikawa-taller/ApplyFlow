---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-43
type: convention
title: tests/infrastructure/test_config.py::test_env_example_documents_every_key_without_real_val…
tags: [convention]
created: 2026-08-04
resource: tests/infrastructure/test_config.py, .env.example
---
tests/infrastructure/test_config.py::test_env_example_documents_every_key_without_real_values asserts `.env.example` lists every Settings key but with placeholder (non-real) values, not actual secrets.

## Why
guards against a real credential accidentally being committed into the example file when a new setting is added.

## Where
tests/infrastructure/test_config.py, .env.example
