---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-84
type: architecture
title: Only one code path can press a real submit button on a company's application page
tags: [architecture]
created: 2026-08-04
resource: src/application/use_cases/submit_application_form.py (browser-driving submit) vs. the application-review submit use case (manual-record submit).
---
Only one code path can press a real submit button on a company's application page — gated on four re-checked conditions: the user explicitly triggered it, no human-only boundary (e.g. a CAPTCHA) appeared on the page after filling, every sensitive/legally-attestable filled value has been individually confirmed by the user with no override, and every required field is answered (refused rather than sent, since some portals clear all filled data on a server-side rejection). A second, separate endpoint only records that the user submitted the application manually themselves and never touches the browser.

## Where
src/application/use_cases/submit_application_form.py (browser-driving submit) vs. the application-review submit use case (manual-record submit).
