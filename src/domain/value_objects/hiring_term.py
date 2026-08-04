"""HiringTerm — the academic term a posting is hiring for.

"Summer 2027", "Fall 2026". Internships are advertised against a term rather
than a start date, and a candidate wants exactly one or two of them: someone
looking for Summer 2027 has no use for a Fall 2026 posting, and a list that
mixes them is a list they have to filter by hand.

Why the year is optional
------------------------
Boards routinely publish "Summer Intern" with no year at all — the season is
stated, the year is assumed to be the next one. Guessing which year that is
would be inventing data, and refusing the posting would lose it, so the season
is kept and the year recorded as unknown.

That choice is what `matches()` exists to handle, and it follows the rule the
rest of this domain already uses: an unknown value is never held against
anybody. A posting whose year is unstated matches a candidate looking for any
year of that season, because the alternative is hiding a posting that may well
be the one they want.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.domain.exceptions import InvalidValueError


class TermSeason(StrEnum):
    SPRING = "spring"
    SUMMER = "summer"
    FALL = "fall"
    WINTER = "winter"


_SEASON_LABELS: dict[TermSeason, str] = {
    TermSeason.SPRING: "Spring",
    TermSeason.SUMMER: "Summer",
    TermSeason.FALL: "Fall",
    TermSeason.WINTER: "Winter",
}

#: Bounds on a stated year. Wide enough never to reject a real posting, narrow
#: enough to catch a model that answered with a salary or a page number.
_MIN_YEAR = 2000
_MAX_YEAR = 2100


@dataclass(frozen=True)
class HiringTerm:
    """One academic term, with the year when the posting states it."""

    season: TermSeason
    year: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.season, TermSeason):
            raise InvalidValueError("HiringTerm requires a valid TermSeason.")
        if self.year is None:
            return
        if isinstance(self.year, bool) or not isinstance(self.year, int):
            raise InvalidValueError("HiringTerm.year must be an integer or None.")
        if not _MIN_YEAR <= self.year <= _MAX_YEAR:
            raise InvalidValueError(
                f"HiringTerm.year {self.year} is outside {_MIN_YEAR}-{_MAX_YEAR}; "
                "a value this far out is a misread rather than a real term."
            )

    @property
    def label(self) -> str:
        """ "Summer 2027", or "Summer" when the year is unstated."""
        season = _SEASON_LABELS[self.season]
        return f"{season} {self.year}" if self.year is not None else season

    def matches(self, other: HiringTerm) -> bool:
        """Whether these two terms could be the same term.

        The season must agree. The year only has to agree when *both* sides state
        one — an unstated year on either side is unknown, not a mismatch, and
        treating it as a mismatch would drop postings the candidate wants.

        Symmetric on purpose, so it reads the same whichever side is the
        candidate's wish and whichever is the posting's.
        """
        if self.season is not other.season:
            return False
        if self.year is None or other.year is None:
            return True
        return self.year == other.year
