---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-73
type: config
title: The app's web search provider was migrated from Brave Search (discontinued free tier) to…
tags: [config]
created: 2026-08-04
resource: src/infrastructure/search/tavily_search_client.py (was brave_search_client.py), src/infrastructure/config.py (search_api_base_url now defaults to https://api.tavily.com/search).
---
The app's web search provider was migrated from Brave Search (discontinued free tier) to Tavily, which has a materially different API contract (POST with JSON body vs GET query string, Bearer auth vs X-Subscription-Token header, `results[].content` vs `web.results[].description`).

## Why
Brave no longer offers a free tier; Tavily was chosen as replacement but required a real port, not a string rename.

## Learned
The shared result type was named WebSearchResult (not TavilySearchResult) so a future provider swap only touches one file and its test, not every consumer.

## Where
src/infrastructure/search/tavily_search_client.py (was brave_search_client.py), src/infrastructure/config.py (search_api_base_url now defaults to https://api.tavily.com/search).
