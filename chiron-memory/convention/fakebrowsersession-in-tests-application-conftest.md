---
id: 5e0cba71-7daa-46a2-a753-8759f3df92fb-15
type: convention
title: `FakeBrowserSession` in tests/application/conftest.py is deliberately shared between the…
tags: [convention]
created: 2026-08-04
resource: tests/application/conftest.py.
---
`FakeBrowserSession` in tests/application/conftest.py is deliberately shared between the autofill tests and the review/submit tests, so both halves of the apply flow are exercised against the same recorded session state rather than separate fakes.

## Why
lets tests prove continuity across the autofill→review→submit boundary instead of each half being tested in isolation against divergent fixtures.

## Where
tests/application/conftest.py.
