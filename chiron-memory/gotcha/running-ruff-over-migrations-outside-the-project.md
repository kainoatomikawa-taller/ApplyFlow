---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-35
type: gotcha
title: Running `ruff` over `migrations/` (outside the project's actual `make lint` scope of `src…
tags: [gotcha]
created: 2026-08-04
resource: migrations/
---
Running `ruff` over `migrations/` (outside the project's actual `make lint` scope of `src tests`) auto-reformatted 18 pre-existing migration files (e.g. `Union[...]` → `X | Y`), which then required manual reversion.

## Learned
only lint the directories `make lint` actually covers; a broad `git checkout -- migrations/` cleanup afterward also silently reverted an unrelated real fix (a SecretStr change in migrations/env.py) — always re-verify (e.g. `alembic current`) after any bulk revert.

## Where
migrations/
