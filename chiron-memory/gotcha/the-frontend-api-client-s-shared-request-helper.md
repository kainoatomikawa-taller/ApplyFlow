---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-83
type: gotcha
title: The frontend API client's shared `request()` helper hardcodes `Content-Type
tags: [gotcha]
created: 2026-08-04
resource: frontend/src/api/client.ts.
---
The frontend API client's shared `request()` helper hardcodes `Content-Type: application/json` on every call, which breaks multipart file uploads — FormData needs the browser to set its own boundary, not a fixed JSON header.

## Why
Discovered while wiring the résumé-upload UI into the Profile section; the fix was a separate upload path in the client that bypasses the JSON-only helper rather than forcing JSON onto a file upload.

## Where
frontend/src/api/client.ts.
