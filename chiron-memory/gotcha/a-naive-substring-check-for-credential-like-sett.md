---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-30
type: gotcha
title: A naive substring check for 'credential-like' setting names (matching on `token`)…
tags: [gotcha]
created: 2026-08-04
resource: tests/infrastructure/test_config.py
---
A naive substring check for 'credential-like' setting names (matching on `token`) false-positived on `anthropic_max_tokens`, a non-secret integer setting.

## Learned
use suffix/word-boundary matching for key-name heuristics, not bare substring containment — this is a recurring trap in this codebase (also hit in pii_redaction key-name matching).

## Where
tests/infrastructure/test_config.py
