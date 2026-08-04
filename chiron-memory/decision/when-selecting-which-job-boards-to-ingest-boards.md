---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-102
type: decision
title: When selecting which job boards to ingest, boards were chosen for internship/term signal…
tags: [decision]
created: 2026-08-04
resource: boards.txt
---
When selecting which job boards to ingest, boards were chosen for internship/term signal density, not raw posting volume — e.g. Databricks (806 postings), OpenAI (733), and Gopuff (804) were deliberately skipped for having almost no internships

## Why
every ingested row eventually costs an LLM extraction call, so bulk with no signal is pure cost

## Where
boards.txt
