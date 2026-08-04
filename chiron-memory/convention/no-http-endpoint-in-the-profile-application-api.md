---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-56
type: convention
title: No HTTP endpoint in the profile/application API may take a user id or email as a URL path…
tags: [convention]
created: 2026-08-04
resource: tests/interfaces/http/test_no_pii_in_urls.py and an AST-based log-call-site guard test.
---
No HTTP endpoint in the profile/application API may take a user id or email as a URL path parameter, and log statements may only include ids, section names, and counts — never PII values.

## Why
Enforced by two static guard tests so PII never ends up in URLs (which get logged, cached, sent to analytics) or in application logs.

## Learned
Design new endpoints to derive the subject from the auth token (e.g. get_current_user), never from the URL, and pass only structural identifiers to log calls.

## Where
tests/interfaces/http/test_no_pii_in_urls.py and an AST-based log-call-site guard test.
