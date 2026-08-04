---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-6
type: decision
title: `AtsSafetyValidator` findings are now logged as rule name + `detail` sentence + line…
tags: [decision]
created: 2026-08-04
resource: src/application/use_cases/generate_tailored_resume.py (`_log_ats_findings`), src/domain/services/ats_safety_validator.py.
---
`AtsSafetyValidator` findings are now logged as rule name + `detail` sentence + line number, not the offending resume line itself

## Why
every ATS-safety rule concerns document *formatting* (markdown syntax, table markup, decorative glyphs, etc.), so the rule/detail/line-number triple is sufficient to diagnose without exposing candidate document text

## Where
src/application/use_cases/generate_tailored_resume.py (`_log_ats_findings`), src/domain/services/ats_safety_validator.py.
