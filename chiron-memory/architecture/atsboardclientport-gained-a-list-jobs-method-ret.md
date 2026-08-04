---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-77
type: architecture
title: AtsBoardClientPort gained a `list_jobs` method (returning full postings for a whole…
tags: [architecture]
created: 2026-08-04
resource: src/infrastructure/ats_boards/board_client_base.py.
---
AtsBoardClientPort gained a `list_jobs` method (returning full postings for a whole board), and a new BoardClientBase class implements `find_job` (single-job lookup) once, in terms of `list_jobs`, shared across GreenhouseBoardClient/LeverBoardClient/AshbyBoardClient.

## Why
Removes near-duplicate `__init__`/mapping code across the three clients and guarantees the two questions ("what's on this board" vs "what are this job's details") read the same underlying mapping.

## Where
src/infrastructure/ats_boards/board_client_base.py.
