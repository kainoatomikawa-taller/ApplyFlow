---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-74
type: config
title: SEARCH_API_DAILY_QUOTA (currently defaulted to 100) was sized for Brave's daily-call…
tags: [config]
created: 2026-08-04
resource: src/infrastructure/config.py.
---
SEARCH_API_DAILY_QUOTA (currently defaulted to 100) was sized for Brave's daily-call quota model but Tavily meters monthly credits instead.

## Why
Needs to be reset to roughly the monthly Tavily allowance divided by ~30 to avoid a single bad day silently exhausting the month's credits.

## Where
src/infrastructure/config.py.
