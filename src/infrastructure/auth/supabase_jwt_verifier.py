"""Supabase Auth implementation of the AuthVerifierPort.

Supabase Auth issues HS256 JWTs signed with the project's JWT secret
(Project Settings -> API -> JWT Settings). Verifying the signature here
is enough to authenticate the single account this application supports —
there is no local user table to cross-reference.
"""

from __future__ import annotations

import jwt

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.exceptions import AuthenticationError
from src.application.ports.auth_verifier_port import AuthVerifierPort
from src.infrastructure.config import Settings

_ALGORITHM = "HS256"
_AUDIENCE = "authenticated"  # Supabase's default `aud` claim for logged-in users.


class SupabaseJwtVerifier(AuthVerifierPort):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def verify(self, token: str) -> AuthenticatedUserDTO:
        secret = self._settings.supabase_jwt_secret.get_secret_value()
        if not secret:
            raise AuthenticationError("SUPABASE_JWT_SECRET is not configured.")
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[_ALGORITHM],
                audience=_AUDIENCE,
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid or expired token: {exc}") from exc

        subject = payload.get("sub")
        if not subject:
            raise AuthenticationError("Token is missing a 'sub' claim.")
        return AuthenticatedUserDTO(subject=subject, email=payload.get("email"))
