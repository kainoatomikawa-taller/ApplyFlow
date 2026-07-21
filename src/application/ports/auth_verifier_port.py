"""AuthVerifierPort — abstraction for verifying a caller's bearer token.

Implemented by an auth-provider-specific adapter (e.g. Supabase Auth) in
the infrastructure layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.application.dtos.auth_dtos import AuthenticatedUserDTO


class AuthVerifierPort(ABC):
    """Verifies a bearer token and resolves it to the authenticated user."""

    @abstractmethod
    def verify(self, token: str) -> AuthenticatedUserDTO:
        """Return the authenticated user for a valid token.

        Raises `src.application.exceptions.AuthenticationError` if the
        token is missing, expired, or fails signature verification.
        """
