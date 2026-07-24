"""ClearanceLevel value object — the security clearance a job posting
states it requires or prefers."""

from __future__ import annotations

from enum import StrEnum


class ClearanceLevel(StrEnum):
    PUBLIC_TRUST = "public_trust"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"
    TOP_SECRET = "top_secret"
    TOP_SECRET_SCI = "top_secret_sci"
