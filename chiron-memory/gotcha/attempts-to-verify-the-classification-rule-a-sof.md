---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-121
type: gotcha
title: Attempts to verify the classification rule 'a software role at a hedge fund should…
tags: [gotcha]
created: 2026-08-04
---
Attempts to verify the classification rule 'a software role at a hedge fund should classify as software_engineering, not quantitative_finance' failed because live search queries kept matching genuine hybrid postings (e.g. one literally titled 'Quantitative Analyst / Software Developer') rather than an unambiguous plain software role at a finance firm.

## Learned
this industry-vs-function discrimination rule is written into the extraction prompt but remains unverified against a real unambiguous case; the corpus may not contain one.
