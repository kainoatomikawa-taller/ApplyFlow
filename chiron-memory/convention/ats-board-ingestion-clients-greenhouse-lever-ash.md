---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-87
type: convention
title: ATS board ingestion clients (Greenhouse/Lever/Ashby) never infer a field they can't read…
tags: [convention]
created: 2026-08-04
resource: src/infrastructure/ats_boards/.
---
ATS board ingestion clients (Greenhouse/Lever/Ashby) never infer a field they can't read directly: Ashby's is_remote is read as a real boolean, but Greenhouse doesn't publish one so a location string of "Remote" does NOT set the remote flag; salary is left unset rather than guessed from free-text description; an unparseable posted_at date is stored as None, never defaulted to today, so staleness checks can't be fooled by a bad date.

## Where
src/infrastructure/ats_boards/.
