---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-46
type: gotcha
title: A static AST-scanning guard test asserts that only a small allowlisted set of modules may…
tags: [gotcha]
created: 2026-08-04
resource: tests/acceptance/test_sensitive_field_enforcement.py::test_the_eeo_record_is_unreachable_from_every_form_filling_module.
---
A static AST-scanning guard test asserts that only a small allowlisted set of modules may reference EeoSelfIdentification / eeo_self_identification anywhere in src/.

## Why
EEO/demographic data must never leak into anything that fills out application forms — the guard exists to keep that boundary structural, not just a code-review norm.

## Learned
Any new module that touches EEO data (e.g. a profile-editor DTO, mapper, or controller) will fail this test until deliberately added to the allowlist with the reasoning documented — do not try to dodge it by using a differently-named class (e.g. the ORM model name), as the export path does; that's a smuggling trick, not a pattern to copy.

## Where
tests/acceptance/test_sensitive_field_enforcement.py::test_the_eeo_record_is_unreachable_from_every_form_filling_module.
