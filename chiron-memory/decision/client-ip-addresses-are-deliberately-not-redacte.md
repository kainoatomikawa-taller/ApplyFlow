---
id: 8af16910-bbe2-4996-894d-d9d6c39f2aee-11
type: decision
title: Client IP addresses are deliberately NOT redacted by the PII log scrubber
tags: [decision]
created: 2026-08-04
resource: src/infrastructure/observability/pii_redaction.py, docs/decisions/0003-pii-out-of-logs-and-urls.md
---
Client IP addresses are deliberately NOT redacted by the PII log scrubber

## Why
the IPs currently appearing in logs belong to outbound ATS/LLM aggregator hosts, not the candidate — redacting them would remove useful operational signal for no privacy benefit

## Learned
this decision should be revisited if request-logging middleware is ever added, since at that point client IPs would start appearing and would be genuinely PII-adjacent.

## Where
src/infrastructure/observability/pii_redaction.py, docs/decisions/0003-pii-out-of-logs-and-urls.md
