---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-109
type: decision
title: Education standing is modeled as two separate fields, enrollment_status and…
tags: [decision]
created: 2026-08-04
resource: src/domain/value_objects/education_standing.py
---
Education standing is modeled as two separate fields, enrollment_status and degree_in_progress, rather than derived from one another

## Why
a posting can require either independently — "must be a current student" concerns enrollment, "bachelor's required" concerns degree — deriving one from the other would reintroduce the inference this phase was built to remove

## Where
src/domain/value_objects/education_standing.py
