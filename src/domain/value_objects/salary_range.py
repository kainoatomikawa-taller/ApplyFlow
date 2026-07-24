"""SalaryRange value object — a job posting's advertised compensation.

Aggregator sources report salary inconsistently: a single figure, a
min/max band, hourly vs. yearly. This normalizes all of that into one
shape so matching/tailoring never has to branch on where a posting came
from.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.domain.exceptions import InvalidValueError


class SalaryPeriod(StrEnum):
    """The unit a `SalaryRange`'s amounts are denominated in."""

    YEARLY = "yearly"
    HOURLY = "hourly"


@dataclass(frozen=True)
class SalaryRange:
    """A job posting's advertised compensation. At least one of
    `min_amount`/`max_amount` must be present; both may be, for a range."""

    currency: str
    period: SalaryPeriod
    min_amount: float | None = None
    max_amount: float | None = None

    def __post_init__(self) -> None:
        if not self.currency.strip():
            raise InvalidValueError("SalaryRange requires a non-empty currency.")
        if self.min_amount is None and self.max_amount is None:
            raise InvalidValueError(
                "SalaryRange requires at least one of min_amount/max_amount."
            )
        if self.min_amount is not None and self.min_amount < 0:
            raise InvalidValueError("SalaryRange.min_amount cannot be negative.")
        if self.max_amount is not None and self.max_amount < 0:
            raise InvalidValueError("SalaryRange.max_amount cannot be negative.")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise InvalidValueError(
                "SalaryRange.min_amount cannot exceed max_amount."
            )
