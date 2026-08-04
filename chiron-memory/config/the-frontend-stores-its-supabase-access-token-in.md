---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-36
type: config
title: The frontend stores its Supabase access token in `localStorage` (not…
tags: [config]
created: 2026-08-04
resource: frontend/src/api/accessToken.ts
---
The frontend stores its Supabase access token in `localStorage` (not sessionStorage/cookie) so a page reload doesn't log the user out.

## Why
deliberate choice per the file's own comment; noted during the hardening pass's auth/token-handling review, no PII/log issue found there.

## Where
frontend/src/api/accessToken.ts
