"""Address value object — a candidate's mailing address.

Plain contact information; not classified as sensitive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Address:
    """A postal address. Every field is optional — applications ask for
    partial addresses (e.g. city/country only) as often as full ones."""

    street_address: str | None = None
    city: str | None = None
    state_or_region: str | None = None
    postal_code: str | None = None
    country: str | None = None
