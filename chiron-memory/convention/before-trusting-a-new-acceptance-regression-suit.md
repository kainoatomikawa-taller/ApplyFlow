---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-16
type: convention
title: Before trusting a new acceptance/regression suite as sufficient, this project's practice…
tags: [convention]
created: 2026-08-04
resource: demonstrated while building tests/acceptance/test_sensitive_field_enforcement.py.
---
Before trusting a new acceptance/regression suite as sufficient, this project's practice is to mutation-test it manually — reintroduce each known defect one at a time (revert the fix, leak EEO through the policy, leak EEO into the tailoring corpus, drop a stored sponsorship answer) and confirm each is caught by a specific test failure — before finalizing.

## Why
a suite that merely passes doesn't prove it would catch a regression; deliberately reintroducing the bugs it's meant to guard against is the actual proof.

## Where
demonstrated while building tests/acceptance/test_sensitive_field_enforcement.py.
