---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-8
type: gotcha
title: SQLAlchemy's `echo=settings.debug` writes SQL logging to stdout, which corrupts CLI…
tags: [gotcha]
created: 2026-08-04
resource: src/interfaces/cli/main.py — resolved by adding an explicit file-output option to the export/erase CLI commands instead of relying on stdout redirection.
---
SQLAlchemy's `echo=settings.debug` writes SQL logging to stdout, which corrupts CLI commands that print their result (e.g. JSON export) to stdout when debug logging is on

## Why
this made piping `export-data` output to a file unreliable

## Where
src/interfaces/cli/main.py — resolved by adding an explicit file-output option to the export/erase CLI commands instead of relying on stdout redirection.
