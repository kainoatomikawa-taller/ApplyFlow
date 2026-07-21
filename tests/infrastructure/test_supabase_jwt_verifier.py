"""Tests for the Supabase Auth JWT verifier adapter."""

import jwt
import pytest
from pydantic import SecretStr

from src.application.exceptions import AuthenticationError
from src.infrastructure.auth.supabase_jwt_verifier import SupabaseJwtVerifier
from src.infrastructure.config import Settings

SECRET = "test-supabase-jwt-secret-at-least-32-bytes-long"


def _settings(secret: str = SECRET) -> Settings:
    return Settings(_env_file=None, supabase_jwt_secret=SecretStr(secret))


def _token(secret: str = SECRET, **claims: object) -> str:
    payload = {"sub": "user-123", "aud": "authenticated", "email": "dev@example.com"}
    payload.update(claims)
    return jwt.encode(payload, secret, algorithm="HS256")


def test_valid_token_resolves_the_authenticated_user():
    verifier = SupabaseJwtVerifier(_settings())
    user = verifier.verify(_token())
    assert user.subject == "user-123"
    assert user.email == "dev@example.com"


def test_token_signed_with_the_wrong_secret_is_rejected():
    verifier = SupabaseJwtVerifier(_settings())
    with pytest.raises(AuthenticationError):
        verifier.verify(_token(secret="not-the-real-secret"))


def test_token_with_the_wrong_audience_is_rejected():
    verifier = SupabaseJwtVerifier(_settings())
    with pytest.raises(AuthenticationError):
        verifier.verify(_token(aud="some-other-audience"))


def test_token_missing_subject_claim_is_rejected():
    verifier = SupabaseJwtVerifier(_settings())
    token = jwt.encode(
        {"aud": "authenticated", "email": "dev@example.com"}, SECRET, algorithm="HS256"
    )
    with pytest.raises(AuthenticationError):
        verifier.verify(token)


def test_missing_configured_secret_fails_closed():
    verifier = SupabaseJwtVerifier(_settings(secret=""))
    with pytest.raises(AuthenticationError, match="SUPABASE_JWT_SECRET"):
        verifier.verify(_token())
