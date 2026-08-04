---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-85
type: decision
title: When a page has multiple submit buttons (e.g. "Submit application" vs "Submit and create…
tags: [decision]
created: 2026-08-04
---
When a page has multiple submit buttons (e.g. "Submit application" vs "Submit and create an account"), the app asks the user which to press rather than guessing — picking one would silently opt the user into a side effect they never agreed to. If no submit button is visible at all, it hands off to the user rather than clicking the nearest button-shaped element.

## Why
Guessing which control to press is itself an unauthorized action on the candidate's behalf.
