---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-91
type: decision
title: Tavily's search_depth is explicitly set to "basic" (not "advanced") for the ATS…
tags: [decision]
created: 2026-08-04
resource: src/infrastructure/search/tavily_search_client.py / ats_listing_resolver.py.
---
Tavily's search_depth is explicitly set to "basic" (not "advanced") for the ATS board-resolution search.

## Why
"advanced" bills more Tavily credits, and the only question this client ever asks — which ATS host a company's board — is answerable from ordinary first-page results.

## Where
src/infrastructure/search/tavily_search_client.py / ats_listing_resolver.py.
