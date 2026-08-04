---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-101
type: gotcha
title: Matching filters that read extracted requirement fields (e.g. employment_type) have zero…
tags: [gotcha]
created: 2026-08-04
resource: src/application/use_cases/rank_matched_job_postings.py
---
Matching filters that read extracted requirement fields (e.g. employment_type) have zero practical effect until an LLM extraction pass has actually run over the corpus, since requirements defaults to null on all postings

## Learned
don't assume a new filter is "live" just because it typechecks and passes unit tests — check whether extraction has been run against real data

## Where
src/application/use_cases/rank_matched_job_postings.py
