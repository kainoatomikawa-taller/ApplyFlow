---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-126
type: gotcha
title: The LLM job-requirements extractor originally read only `job_posting.description`, never…
tags: [gotcha]
created: 2026-08-05
resource: `JobRequirementsExtractorPort.extract`, `LlmJobRequirementsExtractor`, `ExtractJobRequirements` use case.
---
The LLM job-requirements extractor originally read only `job_posting.description`, never the job title, even though hiring term (e.g. 'Fall 2026') is frequently stated only in the title.

## Why
This caused `term=-` (unknown) extractions for postings whose title literally contained the term, e.g. 'Accounting Intern (Fall 2026)'.

## Learned
Fixed by changing the port signature to `extract(*, title, description)` and including both in the prompt; a caught-early bug via a dry-run on a small slice before bulk-extracting the ~1,900-posting backlog.

## Where
`JobRequirementsExtractorPort.extract`, `LlmJobRequirementsExtractor`, `ExtractJobRequirements` use case.
