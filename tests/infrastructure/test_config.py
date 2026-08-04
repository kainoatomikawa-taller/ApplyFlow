from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from src.infrastructure.config import ConfigurationError, Settings, get_settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent.parent / ".env.example"

#: A syntactically valid 32-byte AES-256 key (base64), for the settings that
#: require one. Not a key anything is encrypted with — these tests never reach
#: the cipher, they only check that configuration is accepted or refused.
_BASE64_KEY = "YXBwbHlmbG93LXRlc3Qta2V5LTMyLWJ5dGVzLSEhISE="


def test_defaults_load_without_any_env_vars():
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.openai_api_key.get_secret_value() == ""


def test_secrets_are_never_exposed_via_repr_or_str():
    settings = Settings(_env_file=None, openai_api_key=SecretStr("sk-super-secret"))
    assert "sk-super-secret" not in repr(settings)
    assert "sk-super-secret" not in str(settings)
    assert "sk-super-secret" not in repr(settings.openai_api_key)


def test_anthropic_api_key_is_never_exposed_via_repr_or_str():
    settings = Settings(
        _env_file=None, anthropic_api_key=SecretStr("sk-ant-super-secret")
    )
    assert "sk-ant-super-secret" not in repr(settings)
    assert "sk-ant-super-secret" not in str(settings)
    assert "sk-ant-super-secret" not in repr(settings.anthropic_api_key)


def test_invalid_environment_fails_fast_with_clear_error():
    with pytest.raises(ValidationError, match="environment"):
        Settings(_env_file=None, environment="not-a-real-env")


def test_missing_openai_key_fails_fast_outside_development():
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            supabase_jwt_secret=SecretStr("jwt-secret"),
            anthropic_api_key=SecretStr("sk-ant-real-key"),
        )


def test_missing_supabase_jwt_secret_fails_fast_outside_development():
    with pytest.raises(ValidationError, match="SUPABASE_JWT_SECRET"):
        Settings(
            _env_file=None,
            environment="production",
            openai_api_key=SecretStr("sk-real-key"),
            anthropic_api_key=SecretStr("sk-ant-real-key"),
        )


def test_missing_anthropic_api_key_fails_fast_outside_development():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            openai_api_key=SecretStr("sk-real-key"),
            supabase_jwt_secret=SecretStr("jwt-secret"),
        )


def test_get_settings_wraps_invalid_config_in_a_clear_error(monkeypatch):
    # `get_settings()` builds its own `Settings`, so unlike every other test here
    # this one cannot pass `_env_file=None` — it has to neutralise the env files
    # from the outside. Without that, a developer's own .env/.env.local supplies
    # some of the required secrets, which changes *which* one fails validation
    # first and so which name appears in the message asserted on below. That made
    # this test pass or fail depending on the machine it ran on.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_missing_field_encryption_keys_fails_fast_outside_development():
    """The one required secret whose absence would not stop the app: without it
    the encryption layer silently falls back to a key committed to this
    repository, so refusing to boot is the only way the mistake is visible."""
    with pytest.raises(ValidationError, match="FIELD_ENCRYPTION_KEYS"):
        Settings(
            _env_file=None,
            environment="production",
            openai_api_key=SecretStr("sk-real-key"),
            supabase_jwt_secret=SecretStr("jwt-secret"),
            anthropic_api_key=SecretStr("sk-ant-real-key"),
            field_blind_index_key=SecretStr(_BASE64_KEY),
        )


def test_missing_blind_index_key_fails_fast_outside_development():
    with pytest.raises(ValidationError, match="FIELD_BLIND_INDEX_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            openai_api_key=SecretStr("sk-real-key"),
            supabase_jwt_secret=SecretStr("jwt-secret"),
            anthropic_api_key=SecretStr("sk-ant-real-key"),
            field_encryption_keys=SecretStr(f"2026-08:{_BASE64_KEY}"),
        )


def test_encryption_keys_are_never_exposed_via_repr_or_str():
    settings = Settings(
        _env_file=None,
        field_encryption_keys=SecretStr(f"2026-08:{_BASE64_KEY}"),
        field_blind_index_key=SecretStr(_BASE64_KEY),
    )
    assert _BASE64_KEY not in repr(settings)
    assert _BASE64_KEY not in str(settings)
    assert _BASE64_KEY not in repr(settings.field_encryption_keys)
    assert _BASE64_KEY not in repr(settings.field_blind_index_key)


def test_all_required_secrets_present_satisfies_non_development_requirement():
    settings = Settings(
        _env_file=None,
        environment="production",
        openai_api_key=SecretStr("sk-real-key"),
        supabase_jwt_secret=SecretStr("jwt-secret"),
        field_encryption_keys=SecretStr(f"2026-08:{_BASE64_KEY}"),
        field_blind_index_key=SecretStr(_BASE64_KEY),
        anthropic_api_key=SecretStr("sk-ant-real-key"),
    )
    assert settings.environment == "production"


def test_env_example_documents_every_key_without_real_values():
    lines = [
        line
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    documented_keys = {line.split("=", 1)[0] for line in lines}

    expected_keys = {name.upper() for name in Settings.model_fields}
    assert expected_keys <= documented_keys

    secret_like_keys = {
        key for key in documented_keys if "KEY" in key or "SECRET" in key
    }
    assert secret_like_keys, "expected at least one secret-like key documented"
    for key in secret_like_keys:
        line = next(line for line in lines if line.startswith(f"{key}="))
        _, _, value = line.partition("=")
        assert value == "", f"{key} must be a placeholder, not a real value"


def test_every_credential_bearing_setting_is_a_secret_str():
    """Credentials must not be spelled out by `repr(settings)`.

    The four connection strings were plain `str` until the Epic 07 hardening
    pass, which meant a debug dump, a stray `print`, or an exception rendering
    its context wrote the database password into a log line. A DSN *is* a
    credential — the password sits in its userinfo — so it belongs in the same
    box as the API keys.

    Asserted over `model_fields` rather than as a fixed list, so a fifth URL or
    a new API key has to make the same decision. `supabase_url` is deliberately
    excluded: it is a project's public API endpoint and carries no secret.
    """
    # Suffix-matched, never substring-matched: `"token" in name` would claim
    # `anthropic_max_tokens`, which is a number. The same trap the log
    # scrubber's key names document (`cache_read_input_tokens`).
    credential_suffixes = (
        "_url",
        "_secret",
        "_key",
        "_keys",
        "_token",
        "_password",
    )
    #: URLs that are public endpoints rather than credentials.
    public_urls = {"supabase_url", "job_aggregator_base_url", "search_api_base_url"}
    credential_like = {
        name
        for name in Settings.model_fields
        if (name.endswith(credential_suffixes) or name == "celery_result_backend")
        and name not in public_urls
    }
    assert credential_like, "expected to find credential-bearing settings"

    plain = {
        name
        for name in credential_like
        if Settings.model_fields[name].annotation is not SecretStr
    }
    assert not plain, (
        "These settings can carry a credential but are not SecretStr, so "
        f"repr(settings) would print them: {sorted(plain)}"
    )


def test_the_database_password_is_not_in_the_settings_repr():
    """The behaviour the typing above exists for, asserted directly."""
    settings = Settings(database_url="postgresql+asyncpg://user:s3cret@db:5432/app")
    assert "s3cret" not in repr(settings)
    assert "s3cret" not in str(settings)
    # And it is still readable by the one caller that needs it.
    assert settings.database_url.get_secret_value().endswith("@db:5432/app")
