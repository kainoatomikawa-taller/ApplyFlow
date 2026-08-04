"""JobSearchPreferences — what kind of work the candidate is looking for.

The first thing in this profile that is a *want* rather than a *fact*. Everything
else — degrees, skills, work authorization — describes the candidate and is
compared against what a posting demands. These describe the search itself and are
compared against what a posting *is*.

That difference is why they carry no `ProvenanceSource`. A provenance tag answers
"who says this is true about you, and may we assert it to an employer"; nothing
here is ever asserted to anyone, and a preference cannot be parsed off a résumé
or inferred from an answer. It is only ever the candidate's own statement, so
recording that would say nothing.

Empty means unstated, never "none"
----------------------------------
An empty set of employment types does not mean the candidate will accept no
work — it means they have not said, and filtering must therefore not narrow
anything. Same rule as `clearance_level` and `highest_degree`, and the same
reason: a gap in the candidate's own data must never cost them postings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.employment_type import EmploymentType
from src.domain.value_objects.hiring_term import HiringTerm
from src.domain.value_objects.job_function import JobFunction

#: Ceilings, not rules about how many kinds of work a person may want — a bound
#: so a malformed payload cannot store an unbounded list.
MAX_EMPLOYMENT_TYPES = 8
MAX_TERMS = 12
MAX_FUNCTIONS = 16

_ValueT = TypeVar("_ValueT", EmploymentType, HiringTerm, JobFunction)


@dataclass(frozen=True)
class JobSearchPreferences:
    """The kinds of role and the terms the candidate wants to see."""

    #: Which engagement shapes to show. Empty = no preference stated.
    employment_types: tuple[EmploymentType, ...] = field(default_factory=tuple)
    #: Which academic terms to show, for term-based roles. Empty = no preference.
    terms: tuple[HiringTerm, ...] = field(default_factory=tuple)
    #: Which kinds of work to show. Empty = no preference stated.
    functions: tuple[JobFunction, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "employment_types",
            _deduplicate(self.employment_types, EmploymentType, "employment type"),
        )
        object.__setattr__(self, "terms", _deduplicate(self.terms, HiringTerm, "term"))
        object.__setattr__(
            self, "functions", _deduplicate(self.functions, JobFunction, "function")
        )
        if len(self.employment_types) > MAX_EMPLOYMENT_TYPES:
            raise InvalidValueError(
                f"At most {MAX_EMPLOYMENT_TYPES} employment types may be stated."
            )
        if len(self.terms) > MAX_TERMS:
            raise InvalidValueError(f"At most {MAX_TERMS} terms may be stated.")
        if len(self.functions) > MAX_FUNCTIONS:
            raise InvalidValueError(f"At most {MAX_FUNCTIONS} functions may be stated.")

    @property
    def is_empty(self) -> bool:
        """True when nothing has been stated, so nothing should be filtered."""
        return not self.employment_types and not self.terms and not self.functions

    @property
    def states_employment_types(self) -> bool:
        return bool(self.employment_types)

    @property
    def states_terms(self) -> bool:
        return bool(self.terms)

    @property
    def states_functions(self) -> bool:
        return bool(self.functions)

    def wants_employment_type(self, employment_type: EmploymentType) -> bool:
        """Whether this type is wanted. True when nothing was stated — silence is
        "show me everything", not "show me nothing"."""
        if not self.employment_types:
            return True
        return employment_type in self.employment_types

    def wants_term(self, term: HiringTerm) -> bool:
        """Whether any stated term could be `term` (see `HiringTerm.matches`)."""
        if not self.terms:
            return True
        return any(wanted.matches(term) for wanted in self.terms)

    def wants_function(self, function: JobFunction) -> bool:
        """Whether this kind of work is wanted. True when nothing was stated."""
        if not self.functions:
            return True
        return function in self.functions


def _deduplicate(
    values: tuple[_ValueT, ...], expected: type, label: str
) -> tuple[_ValueT, ...]:
    """Order-preserving deduplication with a type check.

    Order is the candidate's own priority, so it is kept rather than sorted —
    nothing reads it yet, but a stored ordering that silently reshuffles would be
    a surprise the first time something does.
    """
    seen: list[_ValueT] = []
    for value in values:
        if not isinstance(value, expected):
            raise InvalidValueError(f"Each {label} must be a {expected.__name__}.")
        if value not in seen:
            seen.append(value)
    return tuple(seen)
