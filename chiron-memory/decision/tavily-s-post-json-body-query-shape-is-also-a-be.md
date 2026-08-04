---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-92
type: decision
title: Tavily's POST-JSON-body query shape is also a better fit for the existing PII-out-of-URLs…
tags: [decision]
created: 2026-08-04
resource: docs/decisions/0003-pii-out-of-logs-and-urls.md (updated with a dated note).
---
Tavily's POST-JSON-body query shape is also a better fit for the existing PII-out-of-URLs decision (ADR 0003) than Brave's GET-with-querystring was, since a search term can be a candidate's own name.

## Why
With Tavily, both the API credential and the search query stay out of URLs entirely, closing a gap Brave's design left open.

## Where
docs/decisions/0003-pii-out-of-logs-and-urls.md (updated with a dated note).
