---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-0
type: gotcha
title: `uvicorn.access` (and similar) loggers have `propagate=False` and their own handler, so…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/observability/logging_setup.py
---
`uvicorn.access` (and similar) loggers have `propagate=False` and their own handler, so attaching a `logging.Filter` or custom `Formatter` to the root handler never scrubs them

## Why
filters/formatters attach to handlers, not to the logging pipeline as a whole, so any logger with its own handler bypasses root-level scrubbing

## Learned
PII redaction must be installed via a `logging.setLogRecordFactory` record factory (applies to every LogRecord regardless of handler), not via filters/formatters on the root logger.

## Where
src/infrastructure/observability/logging_setup.py
