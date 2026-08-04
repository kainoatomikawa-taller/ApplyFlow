---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-114
type: decision
title: The three preference axes (employment type, function, term) are independent and a posting…
tags: [decision]
created: 2026-08-04
resource: tests/domain/test_job_search_preference_filter.py
---
The three preference axes (employment type, function, term) are independent and a posting must clear all three to match.

## Why
picking a function should not silently narrow employment types or terms - explicitly tested to catch accidental coupling.

## Where
tests/domain/test_job_search_preference_filter.py
