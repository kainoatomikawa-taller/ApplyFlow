---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-106
type: gotcha
title: The requirements-extractor prompt must explicitly guard against matching the substring…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/llm/llm_job_requirements_extractor.py
---
The requirements-extractor prompt must explicitly guard against matching the substring "intern" inside unrelated words (e.g. "Internal Audit") to avoid false-positive internship classification

## Where
src/infrastructure/llm/llm_job_requirements_extractor.py
