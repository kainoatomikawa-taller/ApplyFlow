"""EmploymentType — the shape of the engagement a posting offers.

Distinct from every other filter in this domain because it is not a requirement
the candidate has to meet. It is a property of the posting that the *candidate*
has a preference about: a current undergraduate looking for a summer internship
does not want a list of senior full-time roles, however well qualified the
matching layer thinks they are.

`NEW_GRAD` is listed alongside `FULL_TIME` rather than folded into it. A
new-graduate role is full-time employment, so on the engagement axis alone the
distinction is arguable — but it is the single most useful line for a student to
filter on, and it moves independently of everything else: a junior wants
internships and not new-grad roles, a graduating senior wants the reverse, and
neither wants ordinary senior full-time postings. Collapsing the two would make
that unexpressible.

Deliberately not modelled here: whether the candidate is *eligible* for the role
(must be a current student, must have graduated). That is a different question
with a different answer source, and it belongs with enrollment status.
"""

from __future__ import annotations

from enum import StrEnum


class EmploymentType(StrEnum):
    #: A fixed-term placement, normally attached to an academic term.
    INTERNSHIP = "internship"
    #: A longer placement alternating with study, often multi-term. Kept apart
    #: from `INTERNSHIP` because co-op programmes have their own eligibility
    #: rules and durations, and a candidate wanting one rarely wants the other.
    CO_OP = "co_op"
    #: Permanent, but explicitly scoped to recent graduates — "new grad",
    #: "university graduate", "early career".
    NEW_GRAD = "new_grad"
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    #: Fixed-term or agency work, including contract-to-hire.
    CONTRACT = "contract"


#: The types a candidate still in education is normally looking for. Not a rule
#: applied anywhere — a convenience for defaulting a new profile's preferences,
#: which the candidate then owns.
STUDENT_EMPLOYMENT_TYPES: frozenset[EmploymentType] = frozenset(
    {EmploymentType.INTERNSHIP, EmploymentType.CO_OP}
)
