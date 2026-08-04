---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-57
type: decision
title: Work-history, education, and skill entries in the profile editor use per-entry…
tags: [decision]
created: 2026-08-04
resource: src/application/use_cases/save_work_history_entry.py, remove_work_history_entry.py (and education/skill equivalents).
---
Work-history, education, and skill entries in the profile editor use per-entry add/edit/delete endpoints (~9 extra endpoints) rather than a single whole-list replace endpoint (~3 endpoints), even though no foreign key references those entry ids.

## Why
Whole-list replace would force re-stamping every entry (including ones never touched, sourced from a résumé) as USER_ENTERED on every save, quietly relabeling parsed facts as user-attested; per-entry writes only touch what actually changed.

## Learned
When provenance/attestation matters, prefer targeted per-item mutation APIs over bulk replace, even when the extra endpoint count seems like pure overhead.

## Where
src/application/use_cases/save_work_history_entry.py, remove_work_history_entry.py (and education/skill equivalents).
