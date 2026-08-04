"""StudentStatusRequirement — what a posting demands about the candidate's
education standing, as opposed to their degrees.

The distinction this exists to make
-----------------------------------
Two internships can both say "bachelor's" and mean opposite things. One wants a
current undergraduate to spend a summer there; the other is for a current
*graduate* student, or for someone who has already finished. `degree_level` alone
cannot tell them apart, which is exactly the case that could not be filtered
before: an undergraduate seeing an internship that requires being a PhD student.

So this is read separately from the degree, and it is a hard requirement — a
posting that says "must be currently enrolled" is not expressing a preference.

`GRADUATED` is the one that changes how degrees are compared
------------------------------------------------------------
For every other value, a degree in progress counts towards a stated degree
requirement, because that is what an internship posting means by "pursuing a
bachelor's". `GRADUATED` is the posting saying it does not — and it is the reason
`HardDisqualifierFilter` has to know about this enum rather than checking
degrees on their own.
"""

from __future__ import annotations

from enum import StrEnum


class StudentStatusRequirement(StrEnum):
    #: Must be enrolled somewhere, at any level.
    CURRENT_STUDENT = "current_student"
    #: Must be enrolled as an undergraduate specifically.
    CURRENT_UNDERGRADUATE = "current_undergraduate"
    #: Must be enrolled on a post-graduate programme specifically.
    CURRENT_GRADUATE_STUDENT = "current_graduate_student"
    #: Must have finished the degree — an in-progress one does not count.
    GRADUATED = "graduated"


#: The values that require the candidate to be studying *now*. Named rather than
#: re-derived at each call site, because "which of these mean enrolled" is the
#: question every consumer asks and getting it wrong silently drops postings.
ENROLLMENT_REQUIRING: frozenset[StudentStatusRequirement] = frozenset(
    {
        StudentStatusRequirement.CURRENT_STUDENT,
        StudentStatusRequirement.CURRENT_UNDERGRADUATE,
        StudentStatusRequirement.CURRENT_GRADUATE_STUDENT,
    }
)
