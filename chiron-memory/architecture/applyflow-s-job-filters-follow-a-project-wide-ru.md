---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-125
type: architecture
title: ApplyFlow's job filters follow a project-wide rule that an unknown/empty field never…
tags: [architecture]
created: 2026-08-05
resource: job filtering/domain services that read `JobRequirements` fields.
---
ApplyFlow's job filters follow a project-wide rule that an unknown/empty field never excludes a posting from results — 'unknown never filters anything out.'

## Why
Some postings genuinely don't state a field (e.g. term), and treating 'unknown' as 'non-match' would silently hide real jobs with no way to distinguish that from there being no matches.

## Learned
This same rule makes 'field not yet extracted' indistinguishable from 'field genuinely unknown,' so filters can appear broken when the real problem is that extraction simply hasn't run yet on the data — check extraction coverage before assuming filter logic is at fault.

## Where
job filtering/domain services that read `JobRequirements` fields.
