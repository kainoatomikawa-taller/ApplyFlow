---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-13
type: gotcha
title: The `erase-data` CLI command requires an explicit `--confirm` flag and prints a clean…
tags: [gotcha]
created: 2026-08-04
resource: src/interfaces/cli/main.py.
---
The `erase-data` CLI command requires an explicit `--confirm` flag and prints a clean refusal message rather than an uncaught traceback when omitted

## Where
src/interfaces/cli/main.py.
