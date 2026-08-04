---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-118
type: architecture
title: Across all preference filters (employment type, function, term), an unknown/None value on…
tags: [architecture]
created: 2026-08-04
resource: job search preference filter logic
---
Across all preference filters (employment type, function, term), an unknown/None value on a posting's requirements never narrows/excludes it - only a known, non-matching value excludes.

## Why
requirements extraction is still incomplete for most postings, so treating unknown as non-matching would hide nearly everything.

## Where
job search preference filter logic
