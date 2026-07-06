"""MatchScore value object — a bounded 0..100 score describing how well a
candidate's resume matches a job description.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.exceptions import InvalidValueError


@dataclass(frozen=True)
class MatchScore:
    """A resume-to-job match score between 0 and 100."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int):
            raise InvalidValueError("Match score must be an integer.")
        if not 0 <= self.value <= 100:
            raise InvalidValueError("Match score must be between 0 and 100.")

    @property
    def is_strong_match(self) -> bool:
        return self.value >= 75

    def __int__(self) -> int:
        return self.value
