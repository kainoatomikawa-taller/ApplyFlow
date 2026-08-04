---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-37
type: decision
title: `pip-audit` found 13 known vulnerabilities, all in `pip`/`setuptools` inside the…
tags: [decision]
created: 2026-08-04
---
`pip-audit` found 13 known vulnerabilities, all in `pip`/`setuptools` inside the scratch/local venv used for the audit — zero known vulnerabilities in actual runtime dependencies (fastapi, sqlalchemy, celery, langchain, etc).

## Why
important not to conflate build-tooling CVEs with the app's real dependency posture when reporting audit results.
