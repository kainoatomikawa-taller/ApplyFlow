---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-45
type: architecture
title: ApplyFlow enforces a hard rule that no application-layer use case may call or depend on…
tags: [architecture]
created: 2026-08-04
resource: src/application/use_cases/*.py.
---
ApplyFlow enforces a hard rule that no application-layer use case may call or depend on another use case.

## Why
Keeps use cases independent and single-purpose; cross-use-case dependencies must instead go through shared repository/port calls (e.g. UpdateWorkAuthorization injects ConsentRepository directly rather than calling RecordConsent, mirroring how EraseUserData._withdraw_consents already does it).

## Learned
When two features seem to need to call each other, look for a shared repository-level call instead of introducing a use-case-to-use-case dependency.

## Where
src/application/use_cases/*.py.
