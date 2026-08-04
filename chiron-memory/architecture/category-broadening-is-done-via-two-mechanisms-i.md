---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-61
type: architecture
title: Category broadening is done via two mechanisms in priority order
tags: [architecture]
created: 2026-08-04
resource: src/domain/services/subject_option_matcher.py.
---
Category broadening is done via two mechanisms in priority order: (1) head-noun/suffix matching (trailing words = the category, e.g. "Computer Engineering"→"Engineering"), then (2) a small curated table for cases word-matching can't derive (Data Analytics↔Data Science, abbreviations like "Comp Sci").

## Why
Suffix-only matching deliberately excludes "Mathematics Education" from matching "Mathematics" (it's an Education degree, not Math), which pure substring matching would get wrong.

## Learned
The curated table is a plain dict, conservative by design — a wrong entry falsely asserts something about the user's education, a missing entry just surfaces the field for manual entry.

## Where
src/domain/services/subject_option_matcher.py.
