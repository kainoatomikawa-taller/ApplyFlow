---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-76
type: decision
title: Added a direct company-board ingest path (`applyflow ingest-board` CLI command,…
tags: [decision]
created: 2026-08-04
resource: src/application/use_cases/ingest_board_jobs.py, src/application/ports/ats_board_client_port.py, src/interfaces/cli/main.py (`ingest-board`).
---
Added a direct company-board ingest path (`applyflow ingest-board` CLI command, IngestBoardJobs use case) that pulls all postings straight from a company's own Greenhouse/Lever/Ashby board, bypassing Adzuna+Tavily entirely.

## Why
Greenhouse/Lever/Ashby board APIs are unauthenticated and unmetered (free, unlimited), but previously were only reachable downstream of an Adzuna search as a repair step for missing fields — meaning the free, high-quality source was gated behind the metered ones. Board postings also have full descriptions (thousands of chars) vs. Adzuna's ~500-char truncated ones.

## Learned
Adzuna+Tavily remain useful for discovery (finding companies you didn't know to look at); direct board ingest is for depth (everything a known target company has posted) and costs nothing.

## Where
src/application/use_cases/ingest_board_jobs.py, src/application/ports/ats_board_client_port.py, src/interfaces/cli/main.py (`ingest-board`).
