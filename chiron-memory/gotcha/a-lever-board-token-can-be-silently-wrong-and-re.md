---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-103
type: gotcha
title: A Lever board token can be silently wrong and return 0 postings without erroring, which…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure (Lever board client)
---
A Lever board token can be silently wrong and return 0 postings without erroring, which looks identical to "this company has zero internships"

## Learned
verify a suspicious all-zero result against the Lever API directly (e.g. curl) before concluding the client/board itself is broken

## Where
src/infrastructure (Lever board client)
