"""ProvenanceSource value object — where a stored fact came from.

Every fact ApplyFlow stores about a candidate — a work history entry, a
skill, a contact detail, a sensitive field — is labeled with exactly one of
these sources. This is a first-class attribute of the data model, not a
retrofit: a fact cannot be constructed, let alone persisted, without one
(see the `source`/`*_source` fields on `WorkHistoryEntry`, `EducationEntry`,
`Skill`, `WorkAuthorization`, `EeoSelfIdentification`, and `UserProfile`).

Downstream contract (Epic 04 — tailoring/generation): generated output
(tailored resumes, cover letters, autofilled application answers) may only
assert facts that carry a real `ProvenanceSource` read from this data
model. Epic 04 must never fabricate a fact and present it as if it came
from the candidate — every claim it makes has to trace back to one of
these three sources, and code reviews for Epic 04 should reject any code
path that invents a value instead of reading one through the data-access
layer.
"""

from __future__ import annotations

from enum import StrEnum


class ProvenanceSource(StrEnum):
    """Where a stored fact originated."""

    PARSED_RESUME = "parsed_resume"
    USER_ENTERED = "user_entered"
    ANSWER = "answer"
