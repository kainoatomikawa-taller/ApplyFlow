"""EmailAddress value object — immutable, validated, equality by value."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.domain.exceptions import InvalidValueError

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class EmailAddress:
    """A validated email address."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not _EMAIL_PATTERN.match(normalized):
            raise InvalidValueError(f"'{self.value}' is not a valid email address.")
        # frozen dataclass — bypass immutability to store normalized form
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value
