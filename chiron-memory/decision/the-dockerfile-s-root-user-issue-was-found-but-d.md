---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-32
type: decision
title: The Dockerfile's root-user issue was found but deliberately NOT fixed in this pass and…
tags: [decision]
created: 2026-08-04
resource: Dockerfile, docs/epic-07-hardening-check.md
---
The Dockerfile's root-user issue was found but deliberately NOT fixed in this pass and instead routed as an open finding.

## Why
Docker was unavailable in the working environment to verify an image build, and the change interacts with the compose bind mount and a startup-time `var/resumes` mkdir — an unverified edit to the only deployment artifact was judged riskier than leaving a documented finding.

## Where
Dockerfile, docs/epic-07-hardening-check.md
