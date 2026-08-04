---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-5
type: gotcha
title: EraseUserData must only record a consent 'withdrawal' event for a purpose if consent had…
tags: [gotcha]
created: 2026-08-04
resource: src/application/use_cases/erase_user_data.py.
---
EraseUserData must only record a consent 'withdrawal' event for a purpose if consent had actually been granted for that purpose before

## Why
without this check, erasing a user who never granted a given consent spuriously creates a withdrawal event for a purpose they never opted into

## Where
src/application/use_cases/erase_user_data.py.
