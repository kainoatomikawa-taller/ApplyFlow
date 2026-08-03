---
id: 644dfa30-a7db-462f-a43d-4999b3597642-5
type: architecture
title: Decryption access is scoped only at three authorized entry points
tags: [architecture]
created: 2026-08-03
resource: src/interfaces/http/dependencies.py, src/infrastructure/tasks/analysis_tasks.py, src/interfaces/cli/main.py
---
Decryption access is scoped only at three authorized entry points — get_current_user (HTTP), the Celery analysis task, and the CLI entrypoint — each opens a sensitive_data_access(...) scope.

## Why
satisfies the acceptance criterion that decryption is scoped to authorized access paths only.

## Learned
reading a sensitive-flagged field outside one of these scopes raises rather than silently returning plaintext.

## Where
src/interfaces/http/dependencies.py, src/infrastructure/tasks/analysis_tasks.py, src/interfaces/cli/main.py
