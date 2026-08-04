---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-111
type: gotcha
title: enrollment_status must be typed EnrollmentStatus | None, where None means "unanswered"…
tags: [gotcha]
created: 2026-08-04
resource: src/domain/value_objects/education_standing.py, src/application/mappers/profile_mapper.py
---
enrollment_status must be typed EnrollmentStatus | None, where None means "unanswered" and NOT_ENROLLED means "candidate has finished studying" — do not default to NOT_ENROLLED and infer answered-ness from other fields

## Why
an earlier design defaulted the field to NOT_ENROLLED and inferred whether the user had answered based on whether other fields were set, which made a genuinely-graduated candidate indistinguishable from one who never opened the section, silently breaking student-only filtering for them

## Where
src/domain/value_objects/education_standing.py, src/application/mappers/profile_mapper.py
