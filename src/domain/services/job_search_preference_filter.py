"""JobSearchPreferenceFilter — does this posting match what the candidate asked
to see?

Deliberately not part of `HardDisqualifierFilter`, which answers the opposite
question. That service asks "does the candidate meet what the posting demands"
and removes a job when they provably do not. This one asks "is this the kind of
job the candidate asked for" and removes a job when it provably is not. Both can
drop a posting from a list, but they are different judgements with different
sources of truth, and merging them would produce a service that cannot explain
which kind of mismatch it found.

The practical difference shows up in what a candidate does about a rejection. A
hard disqualifier is something to change about themselves or accept. A preference
mismatch is something to change about the search.

Both rules follow this domain's standing convention: unknown is never held
against anybody. A posting whose employment type could not be extracted is not
hidden from someone who asked for internships, because the honest reading of "we
could not tell" is not "this is not one".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.value_objects.employment_type import EmploymentType
from src.domain.value_objects.hiring_term import HiringTerm
from src.domain.value_objects.job_function import JobFunction
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.job_search_preferences import JobSearchPreferences


@dataclass(frozen=True)
class PreferenceFilterResult:
    """Whether a posting survives the candidate's stated preferences, and if not,
    which preference it failed."""

    matches: bool
    #: Human-readable reasons, one per failed preference. Empty when it matched.
    reasons: tuple[str, ...] = field(default_factory=tuple)


class JobSearchPreferenceFilter:
    """Checks a posting's `JobRequirements` against a candidate's stated
    `JobSearchPreferences`."""

    def evaluate(
        self, preferences: JobSearchPreferences, requirements: JobRequirements
    ) -> PreferenceFilterResult:
        if preferences.is_empty:
            # Nothing stated, so nothing to narrow. Returned early rather than
            # falling through the checks below so the common case — a profile
            # that has never opened the preferences section — costs nothing and
            # can never accidentally filter.
            return PreferenceFilterResult(matches=True)

        reasons: list[str] = []
        self._check_employment_type(preferences, requirements.employment_type, reasons)
        self._check_term(preferences, requirements.hiring_term, reasons)
        self._check_function(preferences, requirements.job_function, reasons)
        return PreferenceFilterResult(matches=not reasons, reasons=tuple(reasons))

    @staticmethod
    def _check_employment_type(
        preferences: JobSearchPreferences,
        employment_type: EmploymentType | None,
        reasons: list[str],
    ) -> None:
        if employment_type is None or not preferences.states_employment_types:
            return
        if preferences.wants_employment_type(employment_type):
            return
        reasons.append(f"This is a {employment_type.value.replace('_', ' ')} role")

    @staticmethod
    def _check_function(
        preferences: JobSearchPreferences,
        job_function: JobFunction | None,
        reasons: list[str],
    ) -> None:
        """Filter a posting whose kind of work the candidate did not ask for.

        Same unknown rule as the other two, and it matters more here: a posting's
        function is inferred from its prose by a model, so "could not tell" is a
        genuinely common outcome. Hiding those would silently shrink the list in a
        way indistinguishable from there being no such jobs.
        """
        if job_function is None or not preferences.states_functions:
            return
        if preferences.wants_function(job_function):
            return
        reasons.append(f"This is a {job_function.value.replace('_', ' ')} role")

    @staticmethod
    def _check_term(
        preferences: JobSearchPreferences,
        hiring_term: HiringTerm | None,
        reasons: list[str],
    ) -> None:
        if hiring_term is None or not preferences.states_terms:
            return
        if preferences.wants_term(hiring_term):
            return
        reasons.append(f"This is for {hiring_term.label}")
