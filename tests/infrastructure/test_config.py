from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from src.infrastructure.config import ConfigurationError, Settings, get_settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent.parent / ".env.example"


def test_defaults_load_without_any_env_vars():
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.openai_api_key.get_secret_value() == ""


def test_secrets_are_never_exposed_via_repr_or_str():
    settings = Settings(_env_file=None, openai_api_key=SecretStr("sk-super-secret"))
    assert "sk-super-secret" not in repr(settings)
    assert "sk-super-secret" not in str(settings)
    assert "sk-super-secret" not in repr(settings.openai_api_key)


def test_invalid_environment_fails_fast_with_clear_error():
    with pytest.raises(ValidationError, match="environment"):
        Settings(_env_file=None, environment="not-a-real-env")


def test_missing_openai_key_fails_fast_outside_development():
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(_env_file=None, environment="production")


def test_get_settings_wraps_invalid_config_in_a_clear_error(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_openai_key_present_satisfies_non_development_requirement():
    settings = Settings(
        _env_file=None,
        environment="production",
        openai_api_key=SecretStr("sk-real-key"),
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
