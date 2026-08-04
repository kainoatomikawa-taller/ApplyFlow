---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-65
type: gotcha
title: ANTHROPIC_MAX_TOKENS was a single global 1024-token output cap applied to every LLM call…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/llm/anthropic_client.py, src/application/ports/llm_client_port.py (TASK_TYPE_MAX_TOKENS).
---
ANTHROPIC_MAX_TOKENS was a single global 1024-token output cap applied to every LLM call (résumé parsing, cover letters, matching rationale), causing résumé parsing on real (longer) résumés to truncate mid-JSON and fail with "Unterminated string" errors.

## Why
Résumé-to-JSON is by far the largest structured output the app produces; short-rationale tasks fit under 1024 tokens so the bug was invisible in smaller test cases.

## Learned
Fixed with per-task-type output budgets (résumé parsing/tailoring: 8192, requirement extraction/cover letter: 4096, matching/rationale: 2048); ANTHROPIC_MAX_TOKENS is now a floor, not a ceiling. The client also now checks stop_reason and raises rather than silently returning truncated text.

## Where
src/infrastructure/llm/anthropic_client.py, src/application/ports/llm_client_port.py (TASK_TYPE_MAX_TOKENS).
