---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-94
type: gotcha
title: Autofill has no live progress feed
tags: [gotcha]
created: 2026-08-04
resource: src/interfaces/http/controllers/application_autofill_controller.py.
---
Autofill has no live progress feed — the whole pass is one blocking HTTP request that returns a complete field-by-field report plus a base64-encoded PNG screenshot only once finished; there is no streaming (SSE/WebSocket/polling) of decisions as they're made.

## Why
The autofill use case computes the entire report server-side before returning anything, so a slow portal shows only a spinner with no indication of where the pass currently is.

## Where
src/interfaces/http/controllers/application_autofill_controller.py.
