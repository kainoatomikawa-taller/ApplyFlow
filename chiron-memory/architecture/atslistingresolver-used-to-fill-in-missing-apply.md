---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-75
type: architecture
title: AtsListingResolver (used to fill in missing apply URL/description for aggregator-sourced…
tags: [architecture]
created: 2026-08-04
resource: src/infrastructure/search/ats_listing_resolver.py.
---
AtsListingResolver (used to fill in missing apply URL/description for aggregator-sourced listings) caches company→ATS-board resolution permanently in a board cache, so Tavily quota is spent at most once per distinct company ever seen, not once per job listing.

## Learned
This makes Tavily usage cheap in practice even on a limited free-tier plan, since the resolver is also only invoked when a listing actually arrives with missing fields.

## Where
src/infrastructure/search/ats_listing_resolver.py.
