---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-54
type: gotcha
title: ParseResume previously always appended parsed work-history and education entries with no…
tags: [gotcha]
created: 2026-08-04
resource: src/application/use_cases/parse_resume.py (_merge_work_history, _merge_education), using existing normalize_text/titles_match helpers from src/domain/services/text_normalization.py.
---
ParseResume previously always appended parsed work-history and education entries with no deduplication, so re-uploading the same résumé (or uploading after manually entering the same job) doubled the entries.

## Why
Nobody had built the combined manual+résumé workflow before, so the append-only behavior was never exercised the way it now is; skills already deduplicated but work history/education did not.

## Learned
Match on normalized company + title + start date to skip already-present entries when merging parsed résumé data into an existing profile.

## Where
src/application/use_cases/parse_resume.py (_merge_work_history, _merge_education), using existing normalize_text/titles_match helpers from src/domain/services/text_normalization.py.
