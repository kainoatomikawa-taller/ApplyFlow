---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-58
type: decision
title: The profile editor's contact section (name + email) acts as create-or-update and can…
tags: [decision]
created: 2026-08-04
resource: src/application/use_cases/save_contact_details.py.
---
The profile editor's contact section (name + email) acts as create-or-update and can bring a UserProfile into existence from scratch, rather than requiring a résumé upload first.

## Why
User explicitly required that a profile be buildable without ever uploading a résumé — résumé parsing is an optional shortcut, not a prerequisite — and the domain requires full_name + email to exist, so contact is the one section that can create the aggregate; all other sections require a profile to already exist and return a clear error otherwise.

## Learned
When adding a 'from scratch' creation path to an aggregate that previously only got created by one deriving process (résumé parsing), identify the aggregate's minimal required fields and make exactly that section the create-or-update entry point.

## Where
src/application/use_cases/save_contact_details.py.
