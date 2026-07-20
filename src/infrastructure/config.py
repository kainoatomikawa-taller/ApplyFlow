"""Infrastructure configuration.

Environment variables live ONLY in the infrastructure layer, per the
architecture contract. Domain and application never read env vars.

All secret-bearing values are typed as `SecretStr` so they render as
`**********` in reprs, logs, and tracebacks instead of their raw value.
Callers must explicitly call `.get_secret_value()` to obtain the real
value, and should only ever do so right at the point where a third-party
client requires a plain string.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_name: str = "ApplyFlow"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True

    # Database
    database_url: str = (
        "postgresql+asyncpg://applyflow:applyflow@localhost:5432/applyflow"
    )

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # LLM / LangChain (OpenAI — used by LangChainResumeAnalyzer)
    openai_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2

    # Anthropic (reserved for an upcoming Claude-based analyzer)
    anthropic_api_key: SecretStr = SecretStr("")

    # Job aggregator integration (reserved for an upcoming adapter)
    job_aggregator_api_key: SecretStr = SecretStr("")
    job_aggregator_base_url: str = ""

    # Search API integration (reserved for an upcoming adapter)
    search_api_key: SecretStr = SecretStr("")
    search_api_base_url: str = ""

    @model_validator(mode="after")
    def _require_secrets_outside_development(self) -> Settings:
        if self.environment == "development":
            return self
        if not self.openai_api_key.get_secret_value():
            raise ValueError(
                "OPENAI_API_KEY is required when ENVIRONMENT is "
                f"'{self.environment}'."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc
