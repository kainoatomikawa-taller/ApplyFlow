---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-88
type: decision
title: Since enrollment status ("currently pursuing a degree") isn't modeled anywhere in the…
tags: [decision]
created: 2026-08-04
---
Since enrollment status ("currently pursuing a degree") isn't modeled anywhere in the domain yet, the interim recommendation given to a current undergraduate is to set the Qualifications `highest_degree` field to "Bachelor's" rather than the technically-correct "High school" — this correctly filters out Master's/PhD-required postings without misrepresenting the user anywhere, since the field has no ATS form slot and is excluded from the provenance-backed facts a generated résumé/cover letter may cite.

## Why
"High school" is literally accurate but breaks the user's stated goal by also filtering out most bachelor's-required internships and new-grad roles.
