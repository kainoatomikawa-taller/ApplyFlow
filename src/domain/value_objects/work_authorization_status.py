"""WorkAuthorizationStatus value object — a candidate's work-authorization category."""

from __future__ import annotations

from enum import StrEnum


class WorkAuthorizationStatus(StrEnum):
    """How a candidate is authorized to work in their target country."""

    CITIZEN = "citizen"
    PERMANENT_RESIDENT = "permanent_resident"
    VISA_HOLDER = "visa_holder"
    REQUIRES_SPONSORSHIP = "requires_sponsorship"
    NOT_AUTHORIZED = "not_authorized"
    OTHER = "other"
