"""EducationStanding — where the candidate is in their education *now*.

The gap this closes
-------------------
`UserProfile.highest_degree` means highest **completed** degree, and that is all
the profile could say. A current undergraduate therefore had no honest answer:

* "High school" is true, and disqualifies them from every posting that says a
  bachelor's is required — which is most new-grad roles and a great many
  internships, where "bachelor's required" means *in progress*.
* "Bachelor's" gets the right postings and is a false statement.
* Leaving it unset turns degree filtering off entirely, so Master's- and
  PhD-only roles keep appearing.

None of the three is correct, so the field was wrong rather than the candidate's
answer. This adds the missing fact: what they are *currently pursuing*, alongside
what they have finished.

Two fields, not one
-------------------
`enrollment_status` and `degree_in_progress` look redundant and are not.
"Enrolled as an undergraduate" and "pursuing a bachelor's" usually coincide, but a
posting can ask about either — "must be a current student" is a question about
enrolment, and "bachelor's required" is a question about the degree. Answering one
from the other would be inference, and the whole point here is to stop inferring.

`expected_graduation` is what makes a term-based role decidable: a Summer 2027
internship generally requires being enrolled *through* it, which someone
graduating in May 2027 is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.degree_level import DegreeLevel


class EnrollmentStatus(StrEnum):
    #: Not currently studying. The ordinary state for someone in work.
    NOT_ENROLLED = "not_enrolled"
    #: Enrolled on an associate or bachelor's programme.
    UNDERGRADUATE = "undergraduate"
    #: Enrolled on a master's, doctoral, or other post-graduate programme.
    GRADUATE = "graduate"


@dataclass(frozen=True)
class EducationStanding:
    """The candidate's current standing: enrolled or not, on what, until when."""

    #: `None` means the candidate has not answered. `NOT_ENROLLED` is a real
    #: answer — "I have finished studying" — and the two must stay distinct: the
    #: first may never cost anybody a posting, while the second is a fact
    #: eligibility filtering is entitled to act on. An enum member cannot express
    #: "unanswered", which is why this is optional rather than defaulting to
    #: `NOT_ENROLLED`.
    enrollment_status: EnrollmentStatus | None = None
    #: The degree being worked towards. `None` when not enrolled, or when the
    #: candidate has not said which — never guessed from `enrollment_status`.
    degree_in_progress: DegreeLevel | None = None
    expected_graduation: date | None = None

    def __post_init__(self) -> None:
        if self.enrollment_status is not None and not isinstance(
            self.enrollment_status, EnrollmentStatus
        ):
            raise InvalidValueError(
                "EducationStanding requires a valid EnrollmentStatus or None."
            )
        if self.degree_in_progress is not None and not isinstance(
            self.degree_in_progress, DegreeLevel
        ):
            raise InvalidValueError("degree_in_progress must be a DegreeLevel or None.")
        if (
            self.enrollment_status is not EnrollmentStatus.UNDERGRADUATE
            and (self.enrollment_status is not EnrollmentStatus.GRADUATE)
            and (
                self.degree_in_progress is not None
                or self.expected_graduation is not None
            )
        ):
            # Refused rather than silently cleared: "not enrolled, pursuing a
            # master's, graduating 2027" is a contradiction, and the candidate
            # meant one of the two halves. Guessing which would store an answer
            # they did not give.
            raise InvalidValueError(
                "A degree in progress or an expected graduation date requires an "
                "enrollment status of 'undergraduate' or 'graduate'."
            )

    @property
    def is_enrolled(self) -> bool:
        """True only when the candidate said they are studying. Unanswered is
        not enrolled *and* not "not enrolled" — see `is_stated`."""
        return self.enrollment_status in (
            EnrollmentStatus.UNDERGRADUATE,
            EnrollmentStatus.GRADUATE,
        )

    @property
    def is_stated(self) -> bool:
        """Whether the candidate has answered the enrolment question at all.

        This is the discriminator eligibility filtering keys off, and it is a
        plain `is not None` rather than a heuristic over the other two fields —
        which is the point of making the status optional. A candidate who has
        finished studying can now say so and have it honoured, where a scheme
        that defaulted to `NOT_ENROLLED` could not tell that answer apart from
        never having opened the section.
        """
        return self.enrollment_status is not None

    def is_enrolled_through(self, as_of: date) -> bool | None:
        """Whether the candidate is still studying on `as_of`.

        `None` when it cannot be told — not enrolled at all, or enrolled with no
        graduation date given. A caller must treat `None` as unknown and never as
        `False`, which is why this returns three states rather than a bool.
        """
        if not self.is_enrolled:
            return None
        if self.expected_graduation is None:
            return None
        return self.expected_graduation >= as_of
