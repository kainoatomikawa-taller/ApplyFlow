---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-53
type: decision
title: Blank preferred_name falls back to the person's first name (split from full_name) and is…
tags: [decision]
created: 2026-08-04
resource: src/domain/services/profile_field_values.py (_first_name/_preferred_name/_middle_name resolvers).
---
Blank preferred_name falls back to the person's first name (split from full_name) and is flagged as a derived value; blank middle_name is treated as 'no middle name' — left empty when the portal field is optional, but still surfaced to the user when the portal marks it required.

## Why
User-specified product behavior: an ATS 'preferred name' field expects something like 'Mike', not the full legal name; an unfilled optional field is a deliberate statement of absence, but a required field with no value is a genuine conflict only the user can resolve.

## Learned
'Derived' values (assembled from other fields, like first-name-as-fallback) use the existing ProfileFieldValue.is_derived flag so the review screen can show them as inferred rather than user-typed.

## Where
src/domain/services/profile_field_values.py (_first_name/_preferred_name/_middle_name resolvers).
