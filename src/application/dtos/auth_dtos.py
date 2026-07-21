"""Auth-related DTOs.

Carries the identity of the authenticated caller across the port
boundary. This is a single-user application, so the identity is only
ever the one account provisioned with the auth provider.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUserDTO:
    subject: str
    email: str | None
