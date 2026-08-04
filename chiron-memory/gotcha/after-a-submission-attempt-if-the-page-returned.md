---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-86
type: gotcha
title: After a submission attempt, if the page returned still shows a challenge/human-only…
tags: [gotcha]
created: 2026-08-04
---
After a submission attempt, if the page returned still shows a challenge/human-only boundary, the app reports the submission as "not confirmed sent" rather than assuming success.

## Why
Deliberately conservative reporting — a submission that might not have landed must never read as one that did.
