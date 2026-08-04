---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-59
type: decision
title: The profile editor's frontend navigation uses a simple in-app tab switch rather than…
tags: [decision]
created: 2026-08-04
resource: frontend/src/App.tsx.
---
The profile editor's frontend navigation uses a simple in-app tab switch rather than adding a routing library like react-router.

## Why
The app has only about four top-level areas (applications, matches, profile, etc.), which doesn't justify a new dependency.

## Learned
Keep navigation dependency-free for small, flat app structures; only reach for a router when route count or deep-linking needs grow.

## Where
frontend/src/App.tsx.
