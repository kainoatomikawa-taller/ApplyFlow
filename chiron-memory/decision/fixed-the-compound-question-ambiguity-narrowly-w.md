---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-1
type: decision
title: Fixed the compound-question ambiguity narrowly with a `_CONFLICTING_LEGAL_SLOTS` guard…
tags: [decision]
created: 2026-08-04
resource: src/domain/services/ats_field_mapper.py, pinned by a dedicated test in tests/acceptance/test_sensitive_field_enforcement.py.
---
Fixed the compound-question ambiguity narrowly with a `_CONFLICTING_LEGAL_SLOTS` guard scoped only to the authorization/sponsorship pair, rather than a general "any two sensitive slots matched → surface" rule.

## Why
a general rule would also trigger on the canonical, unambiguous sponsorship question (which incidentally also matches "visa status"), incorrectly turning a normal case into a surfaced-for-review case.

## Where
src/domain/services/ats_field_mapper.py, pinned by a dedicated test in tests/acceptance/test_sensitive_field_enforcement.py.
