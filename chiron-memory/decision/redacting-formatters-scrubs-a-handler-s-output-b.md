---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-14
type: decision
title: `redacting_formatters()` scrubs a handler's output by wrapping/subclassing its existing…
tags: [decision]
created: 2026-08-04
resource: src/infrastructure/observability/pii_redaction.py
---
`redacting_formatters()` scrubs a handler's output by wrapping/subclassing its existing `Formatter` rather than mutating its `_fmt`/`_style` attributes in place

## Why
reaching into a formatter's internal `_fmt`/`_style` would silently strip uvicorn's custom colorized console formatter, degrading log readability for an unrelated reason

## Learned
when retrofitting cross-cutting behavior onto third-party logging handlers, wrap the existing formatter object instead of rewriting its internals, to avoid clobbering handler-specific formatting logic you don't own.

## Where
src/infrastructure/observability/pii_redaction.py
