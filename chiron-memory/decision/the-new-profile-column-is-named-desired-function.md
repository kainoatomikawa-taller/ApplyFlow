---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-117
type: decision
title: The new profile column is named desired_functions (not a vaguer name).
tags: [decision]
created: 2026-08-04
resource: migrations/versions/0029_add_desired_functions.py
---
The new profile column is named desired_functions (not a vaguer name).

## Why
keeps room to add an 'industry' field later as an addition rather than having to rename a column that already holds user answers.

## Where
migrations/versions/0029_add_desired_functions.py
