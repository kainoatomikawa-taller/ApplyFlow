---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-42
type: config
title: The frontend (frontend/src) has zero console.log/debug/info/warn/error call sites.
tags: [config]
created: 2026-08-04
resource: frontend/src
---
The frontend (frontend/src) has zero console.log/debug/info/warn/error call sites.

## Why
means the PII-in-logs audit had no frontend log surface to check/redact — backend structured logging is the only place redaction rules need to apply.

## Where
frontend/src
