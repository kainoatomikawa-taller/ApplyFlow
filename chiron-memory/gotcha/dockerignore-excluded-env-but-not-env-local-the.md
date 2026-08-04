---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-31
type: gotcha
title: `.dockerignore` excluded `.env` but not `.env.local` (the file the config layer actually…
tags: [gotcha]
created: 2026-08-04
resource: .dockerignore
---
`.dockerignore` excluded `.env` but not `.env.local` (the file the config layer actually prefers to load) or `var/` (the real résumé-PDF blob store) — both would be baked into image layers by `COPY . .`.

## Learned
dockerignore/gitignore audits must check against what the config loader *actually* reads, not just the canonical `.env` name.

## Where
.dockerignore
