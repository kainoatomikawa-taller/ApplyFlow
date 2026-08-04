---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-13
type: gotcha
title: In `pii_redaction.py`, value-shape rules (email/phone/etc. patterns) must be applied…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/observability/pii_redaction.py
---
In `pii_redaction.py`, value-shape rules (email/phone/etc. patterns) must be applied before the generic `key=value` rule, not after

## Why
the `key=value` pattern is greedy but stops at the first delimiter/space, so if it ran first on a multi-word value (e.g. a street address held in a `location=` field), it would only redact the first word and leave the rest of the PII exposed in the clear

## Learned
rule order in the redaction pipeline is a correctness-critical invariant, not cosmetic — verified via a caplog-based regression test asserting multi-word address values are fully scrubbed.

## Where
src/infrastructure/observability/pii_redaction.py
