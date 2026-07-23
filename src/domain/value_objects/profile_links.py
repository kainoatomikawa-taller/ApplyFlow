"""ProfileLinks value object — a candidate's portfolio/LinkedIn/GitHub URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields

from src.domain.exceptions import InvalidValueError

_URL_PATTERN = re.compile(r"^https?://[^\s]+\.[^\s]+$")


@dataclass(frozen=True)
class ProfileLinks:
    """External links an application commonly asks for. All optional."""

    portfolio_url: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None and not _URL_PATTERN.match(value):
                raise InvalidValueError(f"'{value}' is not a valid {f.name}.")
