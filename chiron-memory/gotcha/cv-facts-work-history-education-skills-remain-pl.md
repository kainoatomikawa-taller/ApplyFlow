---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-38
type: gotcha
title: CV facts (work history, education, skills) remain plaintext in structured columns while…
tags: [gotcha]
created: 2026-08-04
resource: flagged as the largest residual/routed finding in docs/epic-07-hardening-check.md
---
CV facts (work history, education, skills) remain plaintext in structured columns while `resumes.extracted_text` — the same underlying facts as raw text — is already encrypted.

## Why
encryption coverage was checked per-column, not per-fact, so the same PII can be protected in one representation and exposed in another; this is the leading open item for the next hardening pass.

## Where
flagged as the largest residual/routed finding in docs/epic-07-hardening-check.md
