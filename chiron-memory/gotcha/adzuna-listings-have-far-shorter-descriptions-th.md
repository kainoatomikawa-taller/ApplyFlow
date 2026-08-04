---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-105
type: gotcha
title: Adzuna listings have far shorter descriptions than direct ATS boards (~500 chars avg vs.…
tags: [gotcha]
created: 2026-08-04
resource: job_postings table, source='adzuna'
---
Adzuna listings have far shorter descriptions than direct ATS boards (~500 chars avg vs. 1,887–6,053 for Lever/Greenhouse/Ashby)

## Why
aggregator truncation means hiring-term extraction will often be impossible on Adzuna rows — worth accounting for when tuning the extraction prompt or evaluating extractor recall

## Where
job_postings table, source='adzuna'
