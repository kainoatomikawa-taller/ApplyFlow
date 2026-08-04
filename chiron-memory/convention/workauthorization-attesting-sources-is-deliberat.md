---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-49
type: convention
title: WorkAuthorization.ATTESTING_SOURCES is deliberately {USER_ENTERED, ANSWER} and excludes…
tags: [convention]
created: 2026-08-04
resource: src/domain/value_objects/work_authorization.py.
---
WorkAuthorization.ATTESTING_SOURCES is deliberately {USER_ENTERED, ANSWER} and excludes PARSED_RESUME.

## Why
A wrong job title from résumé parsing is a cosmetic error, but an autofilled work-authorization/visa answer that's wrong is a legally serious mistake, so only data the candidate directly typed or explicitly answered is trusted enough to autofill; decide_sensitive_field refuses anything unattested.

## Learned
Any new write path for work authorization must stamp USER_ENTERED (or ANSWER) — never PARSED_RESUME or any other source — or the data will be silently unusable for autofill despite being stored.

## Where
src/domain/value_objects/work_authorization.py.
